"""Real PostgreSQL + Temporal lifecycle, with simulated Twilio HTTP calls only."""
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import settings
from app.core.messaging_delivery import deliver_message
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.auth import Membership, MembershipRole, Organization, User
from app.models.campaign import Campaign, CampaignAudit, CampaignRecipient, MarketingConsent
from app.models.crm import Contact
from app.models.messaging import OutboundMessage
from app.temporal.campaigns import CampaignWorkflow, tick


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_CAMPAIGNS") != "1", reason="Real PostgreSQL and Temporal test is opt-in")
async def test_campaign_end_to_end_recovers_after_worker_restart(monkeypatch):
    engine=create_async_engine(settings.database_url)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    org_id,user_id=uuid.uuid4(),uuid.uuid4()
    email=f"campaign-test-{user_id}@example.com"
    for key,value in {"twilio_account_sid":"sandbox-account", "twilio_auth_token":"sandbox-token",
        "twilio_from_number":"+12025550199","campaign_sms_interval_seconds":0}.items():
        monkeypatch.setattr(settings,key,value)
    async def database():
        async with sessions() as db:yield db
    app.dependency_overrides[get_db]=database
    temporal=await Client.connect(settings.temporal_address,namespace=settings.temporal_namespace)
    queue=f"campaign-sandbox-{uuid.uuid4()}"
    first_tick=asyncio.Event()
    provider=AsyncMock()
    provider.__aenter__.return_value=provider
    provider.post.return_value=httpx.Response(201,json={"sid":"SM-simulated-only"},request=httpx.Request("POST","https://api.twilio.com/test"))
    @activity.defn(name="campaign_tick")
    async def sandbox_tick(payload:dict)->dict:
        # A real DB and the production activity logic; only external delivery is simulated.
        with patch("app.core.messaging_delivery.httpx.AsyncClient",return_value=provider):
            result=await tick(payload,sessions,deliver_message)
        first_tick.set()
        return result
    handle=None
    try:
        async with sessions() as db:
            db.add_all([User(id=user_id,email=email,full_name="Sandbox Owner",password_hash=hash_password("SandboxOnly123!"),is_email_verified=True),Organization(id=org_id,name="Campaign sandbox",slug=f"campaign-sandbox-{org_id}")])
            await db.flush()
            db.add(Membership(user_id=user_id,organization_id=org_id,role=MembershipRole.admin))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as api:
            login=await api.post("/api/v1/auth/login",json={"email":email,"password":"SandboxOnly123!"})
            assert login.status_code==200,login.text
            headers={"X-Organization-ID":str(org_id),"X-CSRF-Token":login.json()["csrf_token"]}
            contact=await api.post("/api/v1/crm/contacts",headers=headers,json={"name":"Synthetic Contact","phone":"+12025550123","email":"synthetic@example.com"})
            assert contact.status_code==201,contact.text
            response=await api.post("/api/v1/campaigns/consents",headers=headers,json={"contact_id":contact.json()["id"],"channel":"sms","granted":True,"evidence":"Synthetic sandbox consent, never a real subscriber"})
            assert response.status_code==200,response.text
            campaign=await api.post("/api/v1/campaigns",headers=headers,json={"name":"Sandbox recovery", "channel":"sms","body":"Hello {{first_name}}","scheduled_at":(datetime.now(UTC)+timedelta(seconds=8)).isoformat()})
            assert campaign.status_code==201,campaign.text
            campaign_id=campaign.json()["id"]
            for action in ["submit","approve"]:
                response=await api.post(f"/api/v1/campaigns/{campaign_id}/{action}",headers=headers)
                assert response.status_code==200,response.text
            async def start(workflow_id,payload):
                nonlocal handle
                handle=await temporal.start_workflow(CampaignWorkflow.run,payload,id=workflow_id,task_queue=queue)
            async with Worker(temporal,task_queue=queue,workflows=[CampaignWorkflow],activities=[sandbox_tick]):
                with patch("app.api.routes.campaigns.start_campaign_workflow",start):
                    response=await api.post(f"/api/v1/campaigns/{campaign_id}/start",headers=headers)
                assert response.status_code==200,response.text
                await asyncio.wait_for(first_tick.wait(),15)
            # The durable scheduled timer survives replacement of the actual worker.
            async with Worker(temporal,task_queue=queue,workflows=[CampaignWorkflow],activities=[sandbox_tick]):
                result=await asyncio.wait_for(handle.result(),45)
            assert result["status"]=="completed"
            assert provider.post.await_count==1
            stats=(await api.get(f"/api/v1/campaigns/{campaign_id}/analytics",headers=headers)).json()
            assert stats["statuses"]=={"accepted":1} and stats["total"]==1
            assert len(stats["attempts"])==1
    finally:
        if handle:
            try:await handle.terminate("Sandbox cleanup")
            except Exception:pass
        app.dependency_overrides.pop(get_db,None)
        async with sessions() as db:
            # Delete only the synthetic organization created by this test.
            await db.execute(delete(Organization).where(Organization.id==org_id))
            await db.execute(delete(User).where(User.id==user_id))
            await db.commit()
        await engine.dispose()
