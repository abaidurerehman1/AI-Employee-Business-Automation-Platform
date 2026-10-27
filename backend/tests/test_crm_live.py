import asyncio
import json
import os
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client

from app.core.config import settings
from app.core.temporal_client import start_tool_workflow
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.agent import Agent, AgentConversation, AgentToolRequest, AgentVersion
from app.models.auth import Membership, MembershipRole, Organization, User
from app.models.crm import Contact, Lead


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Requires PostgreSQL and Temporal worker")
@pytest.mark.parametrize("tool_name", ["search_crm_contacts", "search_crm_leads"])
@pytest.mark.parametrize("has_membership", [True, False])
async def test_crm_agent_tool_respects_organization_and_membership(tool_name, has_membership):
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, foreign_id, agent_id, version_id, request_id = (uuid4() for _ in range(6))
    workflow_id = f"crm-test-{request_id}"
    try:
        async with sessions() as db:
            db.add_all([User(id=user_id, email=f"crm-{user_id}@example.com", full_name="Test", password_hash="unused"),
                        Organization(id=org_id, name="Test", slug=f"crm-{org_id}"),
                        Organization(id=foreign_id, name="Other", slug=f"crm-{foreign_id}")])
            await db.flush()
            if has_membership:
                db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.employee))
            db.add_all([Contact(organization_id=org_id, name="Raven local", email="local@example.com"),
                        Contact(organization_id=foreign_id, name="Raven secret", email="secret@example.com"),
                        Lead(organization_id=org_id, title="Raven local", stage="new"),
                        Lead(organization_id=foreign_id, title="Raven secret", stage="new"),
                        Agent(id=agent_id, organization_id=org_id, name="Test", status="draft")])
            await db.flush()
            db.add(AgentVersion(id=version_id, agent_id=agent_id, version=1, role="Test", instructions="Test", tone="neutral", language="English", model="test", tools=[tool_name], approval_rules={tool_name: False}))
            await db.flush()
            db.add(AgentToolRequest(id=request_id, organization_id=org_id, agent_id=agent_id, version_id=version_id, requested_by=user_id, tool_name=tool_name, arguments={"query": "Raven"}, workflow_id=workflow_id, status="queued"))
            await db.commit()
        await start_tool_workflow(workflow_id, {"request_id": str(request_id), "requires_approval": False})
        temporal = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        if has_membership:
            result = await asyncio.wait_for(temporal.get_workflow_handle(workflow_id).result(), 30)
            contacts = json.loads(result["result"])
            assert [item["name" if tool_name == "search_crm_contacts" else "title"] for item in contacts] == ["Raven local"]
        else:
            with pytest.raises(Exception):
                await asyncio.wait_for(temporal.get_workflow_handle(workflow_id).result(), 30)
            async with sessions() as db:
                request = await db.get(AgentToolRequest, request_id)
                assert request.status == "failed" and request.result is None
    finally:
        async with sessions() as db:
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.id == request_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.id == version_id))
            await db.execute(delete(Agent).where(Agent.id == agent_id))
            await db.execute(delete(Contact).where(Contact.organization_id.in_([org_id, foreign_id])))
            await db.execute(delete(Lead).where(Lead.organization_id.in_([org_id, foreign_id])))
            await db.execute(delete(Organization).where(Organization.id.in_([org_id, foreign_id])))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_CRM_CHAT") != "1", reason="Requires OpenAI, PostgreSQL and Temporal")
async def test_live_agent_chat_searches_crm():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id = uuid4(), uuid4()
    async def test_db():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = test_db
    try:
        email = f"crm-chat-{user_id}@example.com"
        async with sessions() as db:
            db.add_all([User(id=user_id, email=email, full_name="Test", password_hash=hash_password("Temporary123!"), is_email_verified=True),
                        Organization(id=org_id, name="Test", slug=f"crm-chat-{org_id}")])
            await db.flush()
            db.add_all([Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin),
                        Contact(organization_id=org_id, name="Raven Silver", email="raven.silver@example.com")])
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=90) as client:
            login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Temporary123!"})
            headers = {"X-Organization-ID": str(org_id), "X-CSRF-Token": login.json()["csrf_token"]}
            response = await client.post("/api/v1/agents", headers=headers, json={
                "name": "CRM assistant", "role": "CRM assistant", "instructions": "Use CRM tools when asked to find contacts.",
                "tools": ["search_crm_contacts"], "approval_rules": {"search_crm_contacts": False},
            })
            assert response.status_code == 201, response.text
            agent_id = response.json()["id"]
            chat = await client.post(f"/api/v1/agents/{agent_id}/playground", headers=headers,
                json={"message": "Use the CRM contact search tool to find Raven and give me the email address."})
            assert chat.status_code == 200, chat.text
            assert "raven.silver@example.com" in chat.json()["messages"][-1]["content"].lower()
            requests = await client.get(f"/api/v1/agents/{agent_id}/tool-requests", headers=headers)
            assert any(item["tool_name"] == "search_crm_contacts" and item["status"] == "completed" for item in requests.json())
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.organization_id == org_id))
            await db.execute(delete(AgentConversation).where(AgentConversation.organization_id == org_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(select(Agent.id).where(Agent.organization_id == org_id))))
            await db.execute(delete(Agent).where(Agent.organization_id == org_id))
            await db.execute(delete(Contact).where(Contact.organization_id == org_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
