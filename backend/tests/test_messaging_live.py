import asyncio
import os
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.auth import Membership, MembershipRole, Organization, User
from app.models.messaging import OutboundMessage


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_MESSAGING") != "1", reason="Requires PostgreSQL, Redis and Celery")
async def test_queue_reports_unconfigured_sms_provider_without_sending():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id = uuid4(), uuid4()
    async def test_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = test_db
    try:
        email = f"message-test-{user_id}@example.com"
        async with sessions() as db:
            db.add_all([User(id=user_id, email=email, full_name="Test", password_hash=hash_password("Temporary123!"), is_email_verified=True), Organization(id=org_id, name="Test", slug=f"message-test-{org_id}")])
            await db.flush()
            db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Temporary123!"})
            headers = {"X-Organization-ID": str(org_id), "X-CSRF-Token": login.json()["csrf_token"]}
            result = await client.post("/api/v1/messaging/messages", headers=headers, json={"channel": "sms", "recipient": "+12025550123", "body": "Test", "idempotency_key": "test", "consent_confirmed": True})
            assert result.status_code == 202, result.text
            for _ in range(30):
                items = (await client.get("/api/v1/messaging/messages", headers=headers)).json()
                if items and items[0]["status"] == "failed":
                    break
                await asyncio.sleep(1)
            assert items[0]["status"] == "failed"
            assert "not configured" in items[0]["error_message"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(OutboundMessage).where(OutboundMessage.organization_id == org_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
