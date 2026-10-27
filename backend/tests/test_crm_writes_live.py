import asyncio
import json
import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client, WorkflowFailureError

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.agent import Agent, AgentConversation, AgentMessage, AgentToolRequest, AgentVersion
from app.models.auth import Membership, MembershipRole, Organization, User
from app.models.crm import Company, Contact, Deal, Lead
from app.temporal.activities import execute_crm_write


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_TEMPORAL") != "1", reason="Requires PostgreSQL and Temporal")
async def test_crm_write_approval_idempotency_and_tenant_isolation():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, foreign_org, foreign_contact = (uuid4() for _ in range(4))
    email = f"crm-write-{user_id}@example.com"

    async def test_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        async with sessions() as db:
            db.add_all([
                User(id=user_id, email=email, full_name="Test", password_hash=hash_password("Temporary123!"), is_email_verified=True),
                Organization(id=org_id, name="Test", slug=f"write-{org_id}"),
                Organization(id=foreign_org, name="Other", slug=f"write-{foreign_org}"),
            ])
            await db.flush()
            db.add_all([
                Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin),
                Contact(id=foreign_contact, organization_id=foreign_org, name="Private", email="private@example.com"),
            ])
            await db.commit()
        temporal = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Temporary123!"})
            headers = {"X-Organization-ID": str(org_id), "X-CSRF-Token": login.json()["csrf_token"]}
            agent = await client.post("/api/v1/agents", headers=headers, json={
                "name": "CRM", "role": "Assistant", "instructions": "Help", "tools": ["create_crm_contact", "update_crm_contact", "create_crm_lead", "update_crm_lead", "create_crm_company", "update_crm_company", "create_crm_deal", "update_crm_deal"],
                "approval_rules": {"create_crm_contact": True, "update_crm_contact": True, "create_crm_lead": True, "update_crm_lead": True},
            })
            assert agent.status_code == 201, agent.text
            path = f"/api/v1/agents/{agent.json()['id']}/tool-requests"
            payload = {"tool_name": "create_crm_contact", "arguments": {"name": "Test contact", "email": "test@example.com"}, "idempotency_key": "test-key"}
            pending = await client.post(path, headers=headers, json=payload)
            assert pending.status_code == 201 and pending.json()["status"] == "pending"
            assert (await client.get("/api/v1/crm/contacts", headers=headers)).json()["total"] == 0
            same = await client.post(path, headers=headers, json=payload)
            assert same.json()["id"] == pending.json()["id"]
            changed = {**payload, "arguments": {"name": "Different", "email": "test@example.com"}}
            assert (await client.post(path, headers=headers, json=changed)).status_code == 409
            approved = await client.post(f"{path}/{pending.json()['id']}/approve", headers=headers)
            assert approved.status_code == 200
            outcome = await asyncio.wait_for(temporal.get_workflow_handle(pending.json()["workflow_id"]).result(), 30)
            assert outcome["status"] == "completed"
            result = json.loads(outcome["result"])
            assert result["action"] == "created"
            # Simulate a Temporal activity retry after the transaction committed.
            assert json.loads(await execute_crm_write(sessions, UUID(pending.json()["id"]))) == result
            assert (await client.get("/api/v1/crm/contacts", headers=headers)).json()["total"] == 1
            lead_request = await client.post(path, headers=headers, json={"tool_name": "create_crm_lead", "arguments": {"title": "Prospect"}})
            assert lead_request.status_code == 201
            assert (await client.post(f"{path}/{lead_request.json()['id']}/approve", headers=headers)).status_code == 200
            lead_result = await asyncio.wait_for(temporal.get_workflow_handle(lead_request.json()["workflow_id"]).result(), 30)
            lead_id = json.loads(lead_result["result"])["id"]
            lead_update = await client.post(path, headers=headers, json={"tool_name": "update_crm_lead", "arguments": {"lead_id": lead_id, "title": None, "stage": "qualified"}})
            assert lead_update.status_code == 201
            assert (await client.post(f"{path}/{lead_update.json()['id']}/approve", headers=headers)).status_code == 200
            await asyncio.wait_for(temporal.get_workflow_handle(lead_update.json()["workflow_id"]).result(), 30)
            assert (await client.get(f"/api/v1/crm/leads/{lead_id}", headers=headers)).json()["stage"] == "qualified"
            for entity, create_args, updates in [
                ("company", {"name": "Example company"}, {"name": "Updated company", "website": None}),
                ("deal", {"title": "Example deal", "amount_minor": 100, "currency": "USD"}, {"title": None, "stage": "won", "amount_minor": None, "currency": None}),
            ]:
                created = await client.post(path, headers=headers, json={"tool_name": f"create_crm_{entity}", "arguments": create_args})
                assert created.status_code == 201, created.text
                assert (await client.post(f"{path}/{created.json()['id']}/approve", headers=headers)).status_code == 200
                outcome = await asyncio.wait_for(temporal.get_workflow_handle(created.json()["workflow_id"]).result(), 30)
                entity_id = json.loads(outcome["result"])["id"]
                updated = await client.post(path, headers=headers, json={"tool_name": f"update_crm_{entity}", "arguments": {f"{entity}_id": entity_id, **updates}})
                assert updated.status_code == 201, updated.text
                assert (await client.post(f"{path}/{updated.json()['id']}/approve", headers=headers)).status_code == 200
                outcome = await asyncio.wait_for(temporal.get_workflow_handle(updated.json()["workflow_id"]).result(), 30)
                assert json.loads(outcome["result"])["action"] == "updated"
            rejected = await client.post(path, headers=headers, json={"tool_name": "create_crm_contact", "arguments": {"name": "Rejected", "email": "rejected@example.com"}})
            assert (await client.post(f"{path}/{rejected.json()['id']}/reject", headers=headers)).status_code == 200
            await asyncio.wait_for(temporal.get_workflow_handle(rejected.json()["workflow_id"]).result(), 30)
            assert (await client.get("/api/v1/crm/contacts", headers=headers)).json()["total"] == 1
            update = await client.post(path, headers=headers, json={"tool_name": "update_crm_contact", "arguments": {
                "contact_id": str(foreign_contact), "name": "Unauthorized", "email": None, "phone": None,
            }})
            assert update.status_code == 201
            assert (await client.post(f"{path}/{update.json()['id']}/approve", headers=headers)).status_code == 200
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(temporal.get_workflow_handle(update.json()["workflow_id"]).result(), 30)
            revoked = await client.post(path, headers=headers, json={"tool_name": "create_crm_contact", "arguments": {"name": "Revoked", "email": "revoked@example.com"}})
            assert revoked.status_code == 201
            async with sessions() as db:
                assert (await db.get(Contact, foreign_contact)).name == "Private"
                member = await db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.organization_id == org_id))
                member.role = MembershipRole.employee
                request = await db.get(AgentToolRequest, UUID(revoked.json()["id"]))
                request.decided_by = user_id
                await db.commit()
            with pytest.raises(ValueError, match="manager or administrator"):
                await execute_crm_write(sessions, UUID(revoked.json()["id"]))
            await temporal.get_workflow_handle(revoked.json()["workflow_id"]).cancel()
            denied = await client.post(path, headers=headers, json={"tool_name": "create_crm_contact", "arguments": {"name": "Denied", "email": "denied@example.com"}})
            assert denied.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.organization_id == org_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(select(Agent.id).where(Agent.organization_id == org_id))))
            await db.execute(delete(Agent).where(Agent.organization_id == org_id))
            await db.execute(delete(Contact).where(Contact.organization_id.in_([org_id, foreign_org])))
            await db.execute(delete(Deal).where(Deal.organization_id.in_([org_id, foreign_org])))
            await db.execute(delete(Lead).where(Lead.organization_id.in_([org_id, foreign_org])))
            await db.execute(delete(Company).where(Company.organization_id.in_([org_id, foreign_org])))
            await db.execute(delete(Organization).where(Organization.id.in_([org_id, foreign_org])))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_CRM_CHAT") != "1", reason="Requires OpenAI, PostgreSQL and Temporal")
async def test_live_model_requests_approval_before_creating_contact():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id = uuid4(), uuid4()
    email = f"model-write-{user_id}@example.com"

    async def test_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        async with sessions() as db:
            db.add_all([User(id=user_id, email=email, full_name="Test", password_hash=hash_password("Temporary123!"), is_email_verified=True),
                        Organization(id=org_id, name="Test", slug=f"model-write-{org_id}")])
            await db.flush()
            db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=90) as client:
            login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Temporary123!"})
            headers = {"X-Organization-ID": str(org_id), "X-CSRF-Token": login.json()["csrf_token"]}
            agent = await client.post("/api/v1/agents", headers=headers, json={
                "name": "CRM", "role": "CRM assistant", "instructions": "Use the CRM tool to create contacts when requested.",
                "tools": ["create_crm_contact"], "approval_rules": {"create_crm_contact": True},
            })
            assert agent.status_code == 201, agent.text
            path = f"/api/v1/agents/{agent.json()['id']}"
            response = await client.post(f"{path}/playground", headers=headers, json={"message": "Create a CRM contact named Mia Frost with email mia.frost@example.com using your CRM tool."})
            assert response.status_code == 200, response.text
            requests = (await client.get(f"{path}/tool-requests", headers=headers)).json()
            request = next(item for item in requests if item["tool_name"] == "create_crm_contact")
            assert request["status"] == "pending"
            assert (await client.get("/api/v1/crm/contacts", headers=headers)).json()["total"] == 0
            assert (await client.post(f"{path}/tool-requests/{request['id']}/approve", headers=headers)).status_code == 200
            temporal = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
            await asyncio.wait_for(temporal.get_workflow_handle(request["workflow_id"]).result(), 90)
            contacts = (await client.get("/api/v1/crm/contacts", headers=headers)).json()["items"]
            assert len(contacts) == 1 and contacts[0]["email"] == "mia.frost@example.com"
            conversation = (await client.get(f"{path}/conversations/{response.json()['conversation_id']}", headers=headers)).json()
            assert len(conversation["messages"]) >= 3
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(AgentMessage).where(AgentMessage.conversation_id.in_(select(AgentConversation.id).where(AgentConversation.organization_id == org_id))))
            await db.execute(delete(AgentToolRequest).where(AgentToolRequest.organization_id == org_id))
            await db.execute(delete(AgentConversation).where(AgentConversation.organization_id == org_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(select(Agent.id).where(Agent.organization_id == org_id))))
            await db.execute(delete(Agent).where(Agent.organization_id == org_id))
            await db.execute(delete(Contact).where(Contact.organization_id == org_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
