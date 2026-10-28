"""The development exception must never allow an external campaign recipient."""
import base64
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.campaigns import local_gmail_self_test
from app.core.config import settings
from app.models.messaging import GmailConnection
from tests.test_campaigns import action, campaign_owner, consent, contact, db_run, draft, run_tick


@pytest.mark.parametrize("environment,enabled,provider,url,recipients,expected", [
    ("development", True, "gmail", "http://localhost:8000", ["self@example.com"], True),
    ("development", True, "gmail", "http://127.0.0.1:8000", ["SELF@example.com"], True),
    ("production", True, "gmail", "http://localhost:8000", ["self@example.com"], False),
    ("staging", True, "gmail", "http://localhost:8000", ["self@example.com"], False),
    ("development", False, "gmail", "http://localhost:8000", ["self@example.com"], False),
    ("development", True, "gmail", "http://localhost:8000", ["self@example.com", "other@example.com"], False),
    ("development", True, "gmail", "http://localhost:8000", [], False),
    ("development", True, "resend", "http://localhost:8000", ["self@example.com"], False),
    ("development", True, "gmail", "http://example.com", ["self@example.com"], False),
    ("development", True, "gmail", "", ["self@example.com"], False),
])
def test_local_exception_policy(monkeypatch, environment, enabled, provider, url, recipients, expected):
    monkeypatch.setattr(settings, "app_env", environment)
    monkeypatch.setattr(settings, "campaign_allow_local_gmail_self_test", enabled)
    monkeypatch.setattr(settings, "messaging_public_base_url", url)
    monkeypatch.setattr(settings, "messaging_unsubscribe_secret", "sandbox-signing-key")
    assert local_gmail_self_test({"provider":provider, "sender":"self@example.com"}, recipients) is expected


@pytest.fixture
def local_gmail(client, campaign_owner, monkeypatch):
    key = Fernet.generate_key()
    for name, value in {"google_client_id":"sandbox-client", "google_client_secret":"sandbox-secret",
        "oauth_encryption_key":key.decode(), "app_env":"development", "campaign_allow_local_gmail_self_test":True,
        "messaging_public_base_url":"http://localhost:8000", "messaging_unsubscribe_secret":"sandbox-signing-key",
        "campaign_email_interval_seconds":0}.items():
        monkeypatch.setattr(settings, name, value)
    async def connect(db):
        from app.models.auth import Membership
        from sqlalchemy import select
        organization_id = uuid.UUID(campaign_owner["X-Organization-ID"])
        member = await db.scalar(select(Membership).where(Membership.organization_id == organization_id))
        db.add(GmailConnection(organization_id=organization_id, connected_by=member.user_id, email="self@example.com",
            encrypted_refresh_token=Fernet(key).encrypt(b"sandbox-refresh-token").decode()))
        await db.commit()
    db_run(connect)
    person = contact(client, campaign_owner, email="self@example.com")
    consent(client, campaign_owner, person["id"], channel="email")
    item = draft(client, campaign_owner, channel="email", provider="gmail", subject="Test", audience={"contact_ids":[person["id"]]})
    action(client, campaign_owner, item, "submit")
    return campaign_owner, item


def test_own_gmail_campaign_approves_and_sends_once_with_local_unsubscribe(client, local_gmail, monkeypatch):
    headers, item = local_gmail
    item = action(client, headers, item, "approve")
    with patch("app.api.routes.campaigns.start_campaign_workflow", AsyncMock()):
        action(client, headers, item, "start")
    provider = AsyncMock()
    provider.__aenter__.return_value = provider
    provider.post.side_effect = [
        httpx.Response(200, json={"access_token":"sandbox-access-token"}, request=httpx.Request("POST","https://oauth2.googleapis.com/token")),
        httpx.Response(200, json={"id":"gmail-sandbox-id"}, request=httpx.Request("POST","https://gmail.googleapis.com/send")),
    ]
    for _ in range(4):
        run_tick(client, item, monkeypatch, provider)
    assert provider.post.await_count == 2  # One token refresh and exactly one send.
    encoded = provider.post.await_args_list[1].kwargs["json"]["raw"]
    email = base64.urlsafe_b64decode(encoded).decode()
    assert "To: self@example.com" in email and "http://localhost:8000/api/v1/messaging/unsubscribe/" in email
    assert client.get(f"/api/v1/campaigns/{item['id']}", headers=headers).json()["status"] == "completed"


@pytest.mark.parametrize("change", ["disable", "production"])
def test_development_exception_rechecked_before_dispatch(client, local_gmail, monkeypatch, change):
    headers, item = local_gmail
    item = action(client, headers, item, "approve")
    with patch("app.api.routes.campaigns.start_campaign_workflow", AsyncMock()):
        action(client, headers, item, "start")
    if change == "disable":
        monkeypatch.setattr(settings, "campaign_allow_local_gmail_self_test", False)
    else:
        monkeypatch.setattr(settings, "app_env", "production")
    provider = AsyncMock()
    run_tick(client, item, monkeypatch, provider)
    assert provider.post.await_count == 0
    assert client.get(f"/api/v1/campaigns/{item['id']}", headers=headers).json()["status"] == "failed"


def test_external_recipient_blocks_entire_local_campaign_approval(client, local_gmail):
    headers, _ = local_gmail
    person = contact(client, headers, name="Other Contact", email="other@example.com", phone="+12025550124")
    consent(client, headers, person["id"], channel="email")
    item = draft(client, headers, channel="email", provider="gmail", subject="Test")
    action(client, headers, item, "submit")
    action(client, headers, item, "approve", 422)
