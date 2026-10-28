from unittest.mock import patch
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest
from pathlib import Path
from datetime import UTC, datetime
from svix.webhooks import Webhook
from twilio.request_validator import RequestValidator
from fastapi.testclient import TestClient
from app.db.session import get_db
from app.main import app
from app.models.messaging import OutboundMessage
from tests.test_auth import login, register_and_verify


def headers_for(client, email, org):
    register_and_verify(client, email, org)
    session = login(client, email)
    return {"X-Organization-ID": session["organizations"][0]["id"], "X-CSRF-Token": session["csrf_token"]}


def test_queue_idempotency_and_suppression(client: TestClient):
    headers = headers_for(client, "messaging@example.com", "Team")
    message = {"channel": "email", "recipient": "SARA@example.com", "subject": "Hello", "body": "Welcome", "idempotency_key": "one", "consent_confirmed": True}
    with patch("app.api.routes.messaging.deliver_message_task.delay") as send:
        queued = client.post("/api/v1/messaging/messages", headers=headers, json=message)
        assert queued.status_code == 202, queued.text
        repeated = client.post("/api/v1/messaging/messages", headers=headers, json=message)
        assert repeated.json()["id"] == queued.json()["id"]
        assert send.call_count == 1
        assert client.post("/api/v1/messaging/messages", headers=headers, json={**message, "body": "Different"}).status_code == 409
    assert client.post("/api/v1/messaging/suppressions", headers=headers, json={"channel": "email", "recipient": "sara@example.com"}).status_code == 201
    assert client.post("/api/v1/messaging/messages", headers=headers, json={**message, "idempotency_key": "two"}).status_code == 409
    other = headers_for(client, "other-messaging@example.com", "Other")
    assert client.get("/api/v1/messaging/messages", headers=other).json() == []
    assert client.get("/api/v1/messaging/suppressions", headers=other).json() == []


def test_template_and_phone_validation(client: TestClient):
    headers = headers_for(client, "templates@example.com", "Team")
    template = client.post("/api/v1/messaging/templates", headers=headers, json={"name": "Welcome", "channel": "email", "subject": "Hello", "body": "Welcome"})
    assert template.status_code == 201
    assert len(client.get("/api/v1/messaging/templates", headers=headers).json()) == 1
    message = {"channel": "sms", "recipient": "123", "body": "Hello", "idempotency_key": "bad", "consent_confirmed": True}
    assert client.post("/api/v1/messaging/messages", headers=headers, json=message).status_code == 422


def test_signed_unsubscribe_blocks_future_sends(client: TestClient):
    from app.core.messaging_delivery import unsubscribe_signature
    headers = headers_for(client, "unsubscribe@example.com", "Team")
    message = {"channel": "email", "recipient": "recipient@example.com", "subject": "Hello", "body": "Welcome", "idempotency_key": "first", "consent_confirmed": True}
    with patch("app.api.routes.messaging.deliver_message_task.delay"):
        queued = client.post("/api/v1/messaging/messages", headers=headers, json=message).json()
    with patch("app.core.messaging_delivery.settings.messaging_unsubscribe_secret", "test-secret"):
        signature = unsubscribe_signature(uuid.UUID(queued["id"]))
        assert client.post(f"/api/v1/messaging/unsubscribe/{queued['id']}?signature=invalid").status_code == 404
        assert client.post(f"/api/v1/messaging/unsubscribe/{queued['id']}?signature={signature}").status_code == 200
        assert client.post(f"/api/v1/messaging/unsubscribe/{queued['id']}?signature={signature}").status_code == 200
    assert client.post("/api/v1/messaging/messages", headers=headers, json={**message, "idempotency_key": "second"}).status_code == 409


def test_hourly_limit_rejects_new_messages(client: TestClient):
    headers = headers_for(client, "limit@example.com", "Team")
    message = {"channel": "email", "recipient": "recipient@example.com", "subject": "Hello", "body": "Welcome", "idempotency_key": "first", "consent_confirmed": True}
    with patch("app.api.routes.messaging.deliver_message_task.delay"), patch("app.api.routes.messaging.settings.messaging_hourly_limit", 1):
        assert client.post("/api/v1/messaging/messages", headers=headers, json=message).status_code == 202
        assert client.post("/api/v1/messaging/messages", headers=headers, json={**message, "idempotency_key": "second"}).status_code == 429


def test_unknown_delivery_never_retries_automatically(client: TestClient):
    headers = headers_for(client, "unknown@example.com", "Team")
    message = {"channel": "sms", "recipient": "+12025550123", "body": "Hello", "idempotency_key": "first", "consent_confirmed": True}
    with patch("app.api.routes.messaging.deliver_message_task.delay"):
        queued = client.post("/api/v1/messaging/messages", headers=headers, json=message).json()
    async def mark_unknown():
        async for db in app.dependency_overrides[get_db]():
            item = await db.get(OutboundMessage, uuid.UUID(queued["id"]))
            item.status = "unknown"
            await db.commit()
    asyncio.run(mark_unknown())
    with patch("app.api.routes.messaging.deliver_message_task.delay") as deliver:
        assert client.post(f"/api/v1/messaging/messages/{queued['id']}/retry", headers=headers).status_code == 409
        deliver.assert_not_called()


def test_provider_status_reports_verified_domain(client: TestClient):
    headers = headers_for(client, "provider@example.com", "Team")
    response = MagicMock()
    response.json.return_value = {"data": [{"name": "example.com", "status": "verified"}]}
    provider = AsyncMock()
    provider.get.return_value = response
    provider.__aenter__.return_value = provider
    with patch("app.api.routes.messaging.settings.resend_api_key", "test-key"), patch("app.api.routes.messaging.settings.resend_from_email", "team@example.com"), patch("app.api.routes.messaging.httpx.AsyncClient", return_value=provider):
        status = client.get("/api/v1/messaging/providers", headers=headers)
    assert status.status_code == 200
    assert status.json()["email"]["domain_status"] == "verified"
    assert "test-key" not in status.text


def test_webhook_signatures_status_and_sms_optout(client: TestClient):
    headers = headers_for(client, "webhooks@example.com", "Team")
    email = {"channel": "email", "recipient": "recipient@example.com", "subject": "Hello", "body": "Welcome", "idempotency_key": "email-1", "consent_confirmed": True}
    sms = {"channel": "sms", "recipient": "+12025550123", "subject": "", "body": "Welcome", "idempotency_key": "sms-1", "consent_confirmed": True}
    with patch("app.api.routes.messaging.deliver_message_task.delay"):
        first = client.post("/api/v1/messaging/messages", headers=headers, json=email).json()
        second = client.post("/api/v1/messaging/messages", headers=headers, json=sms).json()
    async def set_ids():
        async for db in app.dependency_overrides[get_db]():
            for item, provider_id in [(first, "email-provider-id"), (second, "SM123")]:
                message = await db.get(OutboundMessage, uuid.UUID(item["id"]))
                message.provider_id, message.status = provider_id, "sent"
            await db.commit()
    asyncio.run(set_ids())
    import base64, json
    secret = "whsec_" + base64.b64encode(b"01234567890123456789012345678901").decode()
    now = datetime.now(UTC)
    event_id = "event-123"
    body = json.dumps({"type": "email.delivered", "data": {"email_id": "email-provider-id"}})
    signature = Webhook(secret).sign(event_id, now, body)
    signature_headers = {"svix-id": event_id, "svix-timestamp": str(int(now.timestamp())), "svix-signature": signature, "Content-Type": "application/json"}
    with patch("app.api.routes.messaging.settings.resend_webhook_secret", secret):
        assert client.post("/api/v1/messaging/webhooks/resend", content=body, headers={**signature_headers, "svix-signature": "bad"}).status_code == 401
        assert client.post("/api/v1/messaging/webhooks/resend", content=body, headers=signature_headers).status_code == 200
        assert client.post("/api/v1/messaging/webhooks/resend", content=body, headers=signature_headers).json()["status"] == "already_received"
        reply_body = json.dumps({"type": "email.received", "data": {"email_id": "received-123", "from": "Recipient <recipient@example.com>"}})
        reply_id = "event-456"
        reply_headers = {"svix-id": reply_id, "svix-timestamp": str(int(now.timestamp())), "svix-signature": Webhook(secret).sign(reply_id, now, reply_body), "Content-Type": "application/json"}
        response = MagicMock()
        response.json.return_value = {"text": "Thank you"}
        provider = AsyncMock()
        provider.get.return_value = response
        provider.__aenter__.return_value = provider
        with patch("app.api.routes.messaging.settings.resend_api_key", "test-key"), patch("app.api.routes.messaging.httpx.AsyncClient", return_value=provider):
            assert client.post("/api/v1/messaging/webhooks/resend", content=reply_body, headers=reply_headers).status_code == 200
        assert any(event["kind"] == "reply" and event["content"] == "Thank you" for event in client.get("/api/v1/messaging/events", headers=headers).json())
    url = f"https://app.example.com/api/v1/messaging/webhooks/twilio/{headers['X-Organization-ID']}"
    form = {"MessageSid": "SM-incoming", "From": "+12025550123", "Body": "STOP"}
    twilio_signature = RequestValidator("test-auth-token").compute_signature(url, form)
    with patch("app.api.routes.messaging.settings.twilio_auth_token", "test-auth-token"), patch("app.api.routes.messaging.settings.messaging_public_base_url", "https://app.example.com"):
        endpoint = f"/api/v1/messaging/webhooks/twilio/{headers['X-Organization-ID']}"
        assert client.post(endpoint, data=form, headers={"X-Twilio-Signature": "bad"}).status_code == 403
        assert client.post(endpoint, data=form, headers={"X-Twilio-Signature": twilio_signature}).status_code == 200
        wrong_org = str(uuid.uuid4())
        wrong_url = f"https://app.example.com/api/v1/messaging/webhooks/twilio/{wrong_org}"
        status_form = {"MessageSid": "SM123", "MessageStatus": "delivered"}
        wrong_signature = RequestValidator("test-auth-token").compute_signature(wrong_url, status_form)
        assert client.post(f"/api/v1/messaging/webhooks/twilio/{wrong_org}", data=status_form, headers={"X-Twilio-Signature": wrong_signature}).status_code == 503
    assert next(item for item in client.get("/api/v1/messaging/messages", headers=headers).json() if item["id"] == first["id"])["status"] == "delivered"
    assert client.get("/api/v1/messaging/suppressions", headers=headers).json()[0]["recipient"] == "+12025550123"


@pytest.mark.asyncio
async def test_delivery_retry_does_not_duplicate_and_suppression_checked():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.core.messaging_delivery import deliver_message
    from app.models.auth import Membership, MembershipRole, Organization, User
    from app.models.messaging import Suppression
    db_file = Path(__file__).parent / f"test-{uuid.uuid4().hex}.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(db_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, first_id, second_id = (uuid.uuid4() for _ in range(4))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([User(id=user_id, email="delivery@example.com", full_name="Test", password_hash="x"), Organization(id=org_id, name="Team", slug="team")])
        await db.flush()
        db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
        db.add_all([OutboundMessage(id=first_id, organization_id=org_id, created_by=user_id, channel="email", recipient="ok@example.com", subject="Hello", body="Hello", idempotency_key="a", status="queued", attempt_count=0),
                    OutboundMessage(id=second_id, organization_id=org_id, created_by=user_id, channel="email", recipient="blocked@example.com", subject="Hello", body="Hello", idempotency_key="b", status="queued", attempt_count=0),
                    Suppression(organization_id=org_id, channel="email", recipient="blocked@example.com", reason="manual")])
        await db.commit()
    response = MagicMock()
    response.json.return_value = {"id": "provider-id"}
    provider = AsyncMock()
    provider.post.return_value = response
    provider.__aenter__.return_value = provider
    with patch("app.core.messaging_delivery.settings.database_url", db_url), patch("app.core.messaging_delivery.settings.resend_api_key", "test"), patch("app.core.messaging_delivery.settings.resend_from_email", "sender@example.com"), patch("app.core.messaging_delivery.settings.messaging_public_base_url", "https://example.com"), patch("app.core.messaging_delivery.settings.messaging_unsubscribe_secret", "secret"), patch("app.core.messaging_delivery.httpx.AsyncClient", return_value=provider):
        await deliver_message(first_id)
        await deliver_message(first_id)
        await deliver_message(second_id)
    assert provider.post.await_count == 1
    assert provider.post.await_args.kwargs["headers"]["Idempotency-Key"] == f"message/{first_id}"
    async with sessions() as db:
        assert (await db.get(OutboundMessage, first_id)).status == "accepted"
        assert (await db.get(OutboundMessage, second_id)).status == "suppressed"
    await engine.dispose()
    db_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_never_retried_automatically():
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.core.messaging_delivery import deliver_message
    from app.models.auth import Membership, MembershipRole, Organization, User
    db_file = Path(__file__).parent / f"test-{uuid.uuid4().hex}.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(db_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, message_id = (uuid.uuid4() for _ in range(3))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([User(id=user_id, email="timeout@example.com", full_name="Test", password_hash="x"), Organization(id=org_id, name="Team", slug="team")])
        await db.flush()
        db.add(Membership(user_id=user_id, organization_id=org_id, role=MembershipRole.admin))
        db.add(OutboundMessage(id=message_id, organization_id=org_id, created_by=user_id, channel="sms", recipient="+12025550123", subject="", body="Hello", idempotency_key="a", status="queued", attempt_count=0))
        await db.commit()
    provider = AsyncMock()
    provider.post.side_effect = httpx.ReadTimeout("timeout")
    provider.__aenter__.return_value = provider
    with patch("app.core.messaging_delivery.settings.database_url", db_url), patch("app.core.messaging_delivery.settings.twilio_account_sid", "test"), patch("app.core.messaging_delivery.settings.twilio_auth_token", "test"), patch("app.core.messaging_delivery.settings.twilio_from_number", "+12025550124"), patch("app.core.messaging_delivery.httpx.AsyncClient", return_value=provider):
        await deliver_message(message_id)
        await deliver_message(message_id)
    assert provider.post.await_count == 1
    async with sessions() as db:
        assert (await db.get(OutboundMessage, message_id)).status == "unknown"
    await engine.dispose()
    db_file.unlink(missing_ok=True)
