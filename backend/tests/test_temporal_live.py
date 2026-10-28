import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.client import Client
from temporalio.worker import Worker
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.core.temporal_client import start_tool_workflow
from app.models.agent import Agent, AgentToolRequest, AgentVersion
from app.models.auth import Membership, MembershipRole, Organization, User
from app.main import app
from app.db.session import get_db
from app.temporal.workflows import AgentToolExecutionWorkflow


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Live Temporal test is opt-in")
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_api_approval_with_real_worker(decision):
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id = uuid4(), uuid4()
    email = f"approval-{user_id}@example.com"
    async def test_db():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = test_db
    try:
        async with sessions() as db:
            db.add_all([User(id=user_id, email=email, full_name="Test", password_hash=hash_password("Temporary123!"), is_email_verified=True),
                        Organization(id=org_id, name="Approval test", slug=f"approval-{org_id}")])
            await db.flush()
            db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Temporary123!"})
            assert login.status_code == 200, login.text
            headers = {"X-Organization-ID": str(org_id), "X-CSRF-Token": login.json()["csrf_token"]}
            agent = await client.post("/api/v1/agents", headers=headers, json={
                "name": "Test", "role": "Test", "instructions": "Help",
                "tools": ["get_current_utc_time"], "approval_rules": {"get_current_utc_time": True},
            })
            assert agent.status_code == 201, agent.text
            agent_id = agent.json()["id"]
            request = await client.post(f"/api/v1/agents/{agent_id}/tool-requests", headers=headers,
                                        json={"tool_name": "get_current_utc_time"})
            assert request.status_code == 201, request.text
            assert request.json()["status"] == "pending"
            request_id = request.json()["id"]
            response = await client.post(f"/api/v1/agents/{agent_id}/tool-requests/{request_id}/{decision}", headers=headers)
            assert response.status_code == 200, response.text
            temporal = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
            await asyncio.wait_for(temporal.get_workflow_handle(request.json()["workflow_id"]).result(), 30)
            rows = (await client.get(f"/api/v1/agents/{agent_id}/tool-requests", headers=headers)).json()
            result = next(item for item in rows if item["id"] == request_id)
            assert result["status"] == ("completed" if decision == "approve" else "rejected")
            assert bool(result["result"]) == (decision == "approve")
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.organization_id == org_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(select(Agent.id).where(Agent.organization_id == org_id))))
            await db.execute(delete(Agent).where(Agent.organization_id == org_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Live Temporal test is opt-in")
async def test_workflow_retries_transient_failure():
    attempts = []

    @activity.defn(name="execute_agent_tool")
    async def execute(payload: dict) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise ApplicationError("Temporary failure")
        return "recovered"

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    queue = f"test-{uuid4()}"
    async with Worker(client, task_queue=queue, workflows=[AgentToolExecutionWorkflow], activities=[execute]):
        result = await asyncio.wait_for(client.execute_workflow(
            AgentToolExecutionWorkflow.run,
            {"request_id": str(uuid4()), "requires_approval": False},
            id=f"test-{uuid4()}", task_queue=queue,
        ), timeout=30)
    assert result == {"status": "completed", "result": "recovered"}
    assert len(attempts) == 2


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Live Temporal test is opt-in")
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_saved_decision_recovers_without_signal(decision):
    executed = []
    resumed = []

    @activity.defn(name="read_tool_decision")
    async def read_decision(request_id: str, expire: bool) -> str:
        return decision

    @activity.defn(name="execute_agent_tool")
    async def execute(payload: dict) -> str:
        executed.append(payload["request_id"])
        return "tool result"

    @activity.defn(name="resume_agent_conversation")
    async def resume(request_id: str) -> str:
        resumed.append(request_id)
        return "resumed"

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    queue = f"test-{uuid4()}"
    request_id = str(uuid4())
    async with Worker(
        client, task_queue=queue, workflows=[AgentToolExecutionWorkflow],
        activities=[read_decision, execute, resume],
    ):
        result = await asyncio.wait_for(
            client.execute_workflow(
                AgentToolExecutionWorkflow.run,
                {"request_id": request_id, "requires_approval": True},
                id=f"test-{uuid4()}", task_queue=queue,
                execution_timeout=timedelta(seconds=30),
            ), timeout=30,
        )
    assert result["status"] == ("completed" if decision == "approve" else "rejected")
    assert executed == ([request_id] if decision == "approve" else [])
    assert resumed == [request_id]


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Live Temporal test is opt-in")
@pytest.mark.parametrize("authority", ["active", "membership_disabled", "approver_demoted"])
async def test_real_worker_recovers_approval_from_database(authority):
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, agent_id, version_id, request_id = (uuid4() for _ in range(5))
    workflow_id = f"integration-{request_id}"
    try:
        async with sessions() as db:
            db.add_all([
                User(id=user_id, email=f"workflow-{user_id}@example.com", full_name="Test", password_hash="unused"),
                Organization(id=org_id, name="Workflow test", slug=f"workflow-{org_id}"),
            ])
            await db.flush()
            db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.employee if authority == "approver_demoted" else MembershipRole.admin, is_active=authority != "membership_disabled"))
            db.add(Agent(id=agent_id, organization_id=org_id, name="Test", status="draft"))
            await db.flush()
            db.add(AgentVersion(id=version_id, agent_id=agent_id, version=1, role="Test", instructions="Test", tone="neutral", language="English", model="test", tools=["get_current_utc_time"], approval_rules={"get_current_utc_time": True}))
            await db.flush()
            db.add(AgentToolRequest(id=request_id, organization_id=org_id, agent_id=agent_id, version_id=version_id, requested_by=user_id, tool_name="get_current_utc_time", arguments={}, workflow_id=workflow_id, status="approved", decided_by=user_id))
            await db.commit()
        await start_tool_workflow(workflow_id, {"request_id": str(request_id), "tool_name": "get_current_utc_time", "arguments": {}, "requires_approval": True})
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        if authority != "active":
            from temporalio.client import WorkflowFailureError
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(client.get_workflow_handle(workflow_id).result(), timeout=30)
            async with sessions() as db:
                request = await db.get(AgentToolRequest, request_id)
                assert request.status == "failed" and request.result is None
            return
        result = await asyncio.wait_for(client.get_workflow_handle(workflow_id).result(), timeout=30)
        assert result["status"] == "completed"
        async with sessions() as db:
            request = await db.get(AgentToolRequest, request_id)
            assert request.status == "completed"
            assert request.result and request.attempt_count == 1
    finally:
        async with sessions() as db:
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.id == request_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.id == version_id))
            await db.execute(delete(Agent).where(Agent.id == agent_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
