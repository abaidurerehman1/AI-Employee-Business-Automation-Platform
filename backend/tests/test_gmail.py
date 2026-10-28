import asyncio
import base64
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db.session import get_db
from app.main import app
from app.models.messaging import GmailConnection
from tests.test_auth import login, register_and_verify


def test_gmail_oauth_session_binding_and_encrypted_token(client: TestClient):
    register_and_verify(client, "gmail-owner@example.com", "Team")
    session = login(client, "gmail-owner@example.com")
    headers = {"X-Organization-ID": session["organizations"][0]["id"], "X-CSRF-Token": session["csrf_token"]}
    storage = {}
    async def store(key, seconds, value):
        storage[key] = value
    async def getdel(key):
        return storage.pop(key, None)
    token = MagicMock()
    token.json.return_value = {"access_token": "test-access-token", "refresh_token": "test-refresh-token"}
    profile = MagicMock()
    profile.json.return_value = {"email": "mail@example.com", "email_verified": True}
    provider = AsyncMock()
    provider.post.return_value = token
    provider.get.return_value = profile
    provider.__aenter__.return_value = provider
    encryption_key = Fernet.generate_key().decode()
    with (patch("app.api.routes.gmail.settings.google_client_id", "client"),
          patch("app.api.routes.gmail.settings.google_client_secret", "secret"),
          patch("app.api.routes.gmail.settings.oauth_encryption_key", encryption_key),
          patch("app.api.routes.gmail.redis_client.setex", side_effect=store),
          patch("app.api.routes.gmail.redis_client.getdel", side_effect=getdel),
          patch("app.api.routes.gmail.httpx.AsyncClient", return_value=provider)):
        start = client.post("/api/v1/messaging/gmail/connect", headers=headers)
        assert start.status_code == 200, start.text
        query = parse_qs(urlparse(start.json()["authorization_url"]).query)
        assert query["code_challenge_method"] == ["S256"]
        state = query["state"][0]
        result = client.get("/api/v1/messaging/gmail/callback", params={"state": state, "code": "test-code"}, follow_redirects=False)
        assert result.status_code == 303, result.text
        status = client.get("/api/v1/messaging/providers", headers=headers).json()
        assert status["gmail"]["connected"] and status["gmail"]["email"] == "mail@example.com"
        assert "test-refresh-token" not in str(status)
        async def read_token():
            async for db in app.dependency_overrides[get_db]():
                connection = await db.scalar(select(GmailConnection))
                return connection.encrypted_refresh_token
        encrypted = asyncio.run(read_token())
        assert "test-refresh-token" not in encrypted
        assert Fernet(encryption_key.encode()).decrypt(encrypted.encode()).decode() == "test-refresh-token"
        assert client.get("/api/v1/messaging/gmail/callback", params={"state": state, "code": "test-code"}, follow_redirects=False).status_code == 400
        assert client.delete("/api/v1/messaging/gmail/connection", headers=headers).status_code == 204


def test_gmail_connect_requires_manager_and_csrf(client: TestClient):
    register_and_verify(client, "gmail-csrf@example.com", "Team")
    session = login(client, "gmail-csrf@example.com")
    headers = {"X-Organization-ID": session["organizations"][0]["id"]}
    assert client.post("/api/v1/messaging/gmail/connect", headers=headers).status_code == 403


def test_gmail_state_cannot_be_used_from_another_login_session(client: TestClient):
    register_and_verify(client, "gmail-state@example.com", "Team")
    first = login(client, "gmail-state@example.com")
    headers = {"X-Organization-ID": first["organizations"][0]["id"], "X-CSRF-Token": first["csrf_token"]}
    storage = {}
    async def store(key, seconds, value):
        storage[key] = value
    async def getdel(key):
        return storage.pop(key, None)
    with (patch("app.api.routes.gmail.settings.google_client_id", "client"), patch("app.api.routes.gmail.settings.google_client_secret", "secret"),
          patch("app.api.routes.gmail.settings.oauth_encryption_key", Fernet.generate_key().decode()),
          patch("app.api.routes.gmail.redis_client.setex", side_effect=store), patch("app.api.routes.gmail.redis_client.getdel", side_effect=getdel)):
        start = client.post("/api/v1/messaging/gmail/connect", headers=headers)
        state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
        login(client, "gmail-state@example.com")
        assert client.get("/api/v1/messaging/gmail/callback", params={"state": state, "code": "test"}, follow_redirects=False).status_code == 403


@pytest.mark.asyncio
async def test_gmail_delivery_uses_connected_account_without_duplicate_retry():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.core.messaging_delivery import deliver_message
    from app.models.auth import Membership, MembershipRole, Organization, User
    from app.models.messaging import OutboundMessage
    path = Path(__file__).parent / f"test-{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, message_id, blocked_id, self_id = (uuid.uuid4() for _ in range(5))
    key = Fernet.generate_key().decode()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([User(id=user_id, email="owner@example.com", full_name="Test", password_hash="x"), Organization(id=org_id, name="Team", slug="team")])
        await db.flush()
        db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
        db.add_all([GmailConnection(organization_id=org_id, connected_by=user_id, email="sender@gmail.com", encrypted_refresh_token=Fernet(key.encode()).encrypt(b"refresh-token").decode()),
                    OutboundMessage(id=message_id, organization_id=org_id, created_by=user_id, channel="email", recipient="person@example.com", subject="Hello", body="Welcome", idempotency_key="one", status="queued", attempt_count=0),
                    OutboundMessage(id=blocked_id, organization_id=org_id, created_by=user_id, channel="email", recipient="other@example.com", subject="Hello", body="Welcome", idempotency_key="two", status="queued", attempt_count=0),
                    OutboundMessage(id=self_id, organization_id=org_id, created_by=user_id, channel="email", recipient="sender@gmail.com", subject="Hello", body="Welcome", idempotency_key="three", status="queued", attempt_count=0)])
        await db.commit()
    token = MagicMock(); token.json.return_value = {"access_token": "access-token"}
    sent = MagicMock(); sent.json.return_value = {"id": "gmail-message-id"}
    provider = AsyncMock(); provider.post.side_effect = [token, sent, token, sent]; provider.__aenter__.return_value = provider
    with (patch("app.core.messaging_delivery.settings.database_url", url), patch("app.core.messaging_delivery.settings.google_client_id", "client"),
          patch("app.core.messaging_delivery.settings.google_client_secret", "secret"), patch("app.core.messaging_delivery.settings.oauth_encryption_key", key),
          patch("app.core.messaging_delivery.settings.messaging_public_base_url", "https://example.com"), patch("app.core.messaging_delivery.settings.messaging_unsubscribe_secret", "test-secret"),
          patch("app.core.messaging_delivery.httpx.AsyncClient", return_value=provider)):
        await deliver_message(message_id)
        await deliver_message(message_id)
        with patch("app.core.messaging_delivery.settings.messaging_public_base_url", "http://localhost:8000"):
            await deliver_message(blocked_id)
            await deliver_message(self_id)
    assert provider.post.await_count == 4
    call = provider.post.await_args_list[1]
    assert call.args[0].startswith("https://gmail.googleapis.com/")
    content = base64.urlsafe_b64decode(call.kwargs["json"]["raw"]).decode()
    assert "sender@gmail.com" in content and "person@example.com" in content and "List-Unsubscribe" in content
    async with sessions() as db:
        assert (await db.get(OutboundMessage, message_id)).status == "accepted"
        assert (await db.get(OutboundMessage, blocked_id)).status == "failed"
        assert (await db.get(OutboundMessage, self_id)).status == "accepted"
    await engine.dispose()
    path.unlink(missing_ok=True)
