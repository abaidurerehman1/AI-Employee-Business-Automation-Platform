"""Account lifecycle and cross-workspace authorization without external delivery."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import has_permission
from app.core.security import token_digest, verify_password
from app.models.auth import AuthSession, EmailToken, Invitation, Membership, MembershipRole, User
from tests.test_auth import login, register_and_verify
from tests.test_campaigns import db_run


def headers(session, organization=None):
    return {
        "X-CSRF-Token": session["csrf_token"],
        "X-Organization-ID": organization or session["organizations"][0]["id"],
    }


def invite(client, session, email, role="employee", organization=None):
    sender = AsyncMock()
    with patch("app.api.routes.organizations.send_invitation_email", sender):
        result = client.post(
            "/api/v1/organizations/current/invitations",
            headers=headers(session, organization),
            json={"email": email, "role": role},
        )
    assert result.status_code == 201, result.text
    return result.json(), sender.await_args.args[2]


def add_member(client, owner, email="employee@example.com", role="employee"):
    _, token = invite(client, owner, email, role)
    register_and_verify(client, email, "Personal workspace")
    client.cookies.clear()
    member = login(client, email)
    assert (
        client.post(
            "/api/v1/organizations/invitations/accept",
            headers=headers(member),
            json={"token": token},
        ).status_code
        == 200
    )
    return member


def test_profile_rotation_password_change_and_session_revocation(client):
    password = "  VerySecure123!  "
    register_and_verify(client, "account@example.com", "Account team", password)
    original = login(client, "account@example.com", password)
    old_cookie = client.cookies.get(settings.session_cookie_name)
    old_csrf = original["csrf_token"]
    assert (
        client.put("/api/v1/auth/account", json={"full_name": "Renamed Person"}).status_code == 403
    )
    assert (
        client.put(
            "/api/v1/auth/account", headers=headers(original), json={"full_name": "Renamed Person"}
        ).json()["user"]["full_name"]
        == "Renamed Person"
    )
    refreshed = client.post("/api/v1/auth/session/rotate", headers=headers(original))
    assert refreshed.status_code == 200, refreshed.text
    rotated_cookie = client.cookies.get(settings.session_cookie_name)
    rotated = refreshed.json()
    assert rotated_cookie != old_cookie and rotated["csrf_token"] != old_csrf
    assert "httponly" in refreshed.headers["set-cookie"].lower()
    assert "samesite=lax" in refreshed.headers["set-cookie"].lower()
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, old_cookie, domain="testserver.local")
    assert client.get("/api/v1/auth/session").status_code == 401
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, rotated_cookie, domain="testserver.local")
    assert (
        client.post("/api/v1/auth/session/rotate", headers={"X-CSRF-Token": old_csrf}).status_code
        == 403
    )
    # A different browser receives its own session, without replacing this one.
    client.cookies.clear()
    login(client, "account@example.com", password)
    other_cookie = client.cookies.get(settings.session_cookie_name)
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, rotated_cookie, domain="testserver.local")
    result = client.post(
        "/api/v1/auth/password",
        headers=headers(rotated),
        json={"current_password": password, "password": "NewSecurePassword123!"},
    )
    assert result.status_code == 200, result.text
    assert len(client.get("/api/v1/auth/sessions").json()) == 1
    assert result.json()["csrf_token"] != rotated["csrf_token"]
    active_cookie = client.cookies.get(settings.session_cookie_name)
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, other_cookie, domain="testserver.local")
    assert client.get("/api/v1/auth/session").status_code == 401
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, active_cookie, domain="testserver.local")
    sessions = client.get("/api/v1/auth/sessions").json()
    assert sessions[0]["current"] and "token_hash" not in sessions[0]
    assert (
        client.delete(
            f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers(result.json())
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/session").status_code == 401
    login(client, "account@example.com", "NewSecurePassword123!")


def test_ownership_member_controls_and_immediate_access_revocation(client):
    register_and_verify(client, "owner@example.com", "Main team")
    owner = login(client, "owner@example.com")
    organization = owner["organizations"][0]["id"]
    assert owner["organizations"][0]["owner_user_id"] == owner["user"]["id"]
    employee = add_member(client, owner)
    employee_cookie = client.cookies.get(settings.session_cookie_name)
    employee_headers = headers(employee, organization)
    assert (
        client.put(
            "/api/v1/organizations/current", headers=employee_headers, json={"name": "Hijacked"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/campaigns", headers=employee_headers).status_code == 403
    assert (
        client.get(
            "/api/v1/organizations/current/security-events", headers=employee_headers
        ).status_code
        == 403
    )
    client.cookies.clear()
    owner = login(client, "owner@example.com")
    auth = headers(owner)
    path = f"/api/v1/organizations/current/members/{owner['user']['id']}"
    assert client.delete(path, headers=auth).status_code == 409
    assert (
        client.put(path, headers=auth, json={"role": "employee", "is_active": True}).status_code
        == 409
    )
    member_path = f"/api/v1/organizations/current/members/{employee['user']['id']}"
    assert (
        client.put(
            member_path, headers=auth, json={"role": "employee", "is_active": False}
        ).status_code
        == 200
    )
    owner_cookie = client.cookies.get(settings.session_cookie_name)
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, employee_cookie)
    assert client.get("/api/v1/crm/contacts", headers=employee_headers).status_code == 404
    assert organization not in {
        org["id"] for org in client.get("/api/v1/auth/session").json()["organizations"]
    }
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, owner_cookie)
    assert (
        client.put(
            member_path, headers=auth, json={"role": "employee", "is_active": True}
        ).status_code
        == 200
    )
    payload = {"user_id": employee["user"]["id"], "current_password": "wrong"}
    assert (
        client.post(
            "/api/v1/organizations/current/ownership", headers=auth, json=payload
        ).status_code
        == 403
    )
    payload["current_password"] = "VerySecure123!"
    assert (
        client.post("/api/v1/organizations/current/ownership", headers=auth, json=payload).json()[
            "owner_user_id"
        ]
        == employee["user"]["id"]
    )
    assert client.delete(member_path, headers=auth).status_code == 409
    assert client.delete(path, headers=auth).status_code == 204
    assert client.get("/api/v1/dashboard", headers=auth).status_code == 404


@pytest.mark.parametrize("invalid", ["revoked", "expired", "inviter_disabled", "replaced"])
def test_invalid_invitations_cannot_grant_access(client, invalid):
    register_and_verify(client, "owner@example.com", "Main team")
    owner = login(client, "owner@example.com")
    invitation, token = invite(client, owner, "invitee@example.com")
    if invalid == "revoked":
        assert (
            client.delete(
                f"/api/v1/organizations/current/invitations/{invitation['id']}",
                headers=headers(owner),
            ).status_code
            == 204
        )
    elif invalid == "replaced":
        invite(client, owner, "invitee@example.com")
    else:

        async def invalidate(db):
            if invalid == "expired":
                item = await db.get(Invitation, uuid.UUID(invitation["id"]))
                item.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                member = await db.scalar(
                    select(Membership).where(Membership.user_id == uuid.UUID(owner["user"]["id"]))
                )
                member.is_active = False
            await db.commit()

        db_run(invalidate)
    client.cookies.clear()
    register_and_verify(client, "invitee@example.com", "Other team")
    invitee = login(client, "invitee@example.com")
    assert (
        client.post(
            "/api/v1/organizations/invitations/accept",
            headers=headers(invitee),
            json={"token": token},
        ).status_code
        == 400
    )


def test_new_workspaces_cross_tenant_routes_and_private_session_ids(client):
    register_and_verify(client, "first@example.com", "First team")
    first = login(client, "first@example.com")
    private_session_id = client.get("/api/v1/auth/sessions").json()[0]["id"]
    created = client.post(
        "/api/v1/organizations", headers=headers(first), json={"name": "Second workspace"}
    )
    assert created.status_code == 201
    refreshed = client.get("/api/v1/auth/session").json()
    assert len(refreshed["organizations"]) == 2
    assert (
        client.put(
            "/api/v1/organizations/current",
            headers=headers(first, created.json()["id"]),
            json={"name": "Updated workspace"},
        ).status_code
        == 200
    )
    register_and_verify(client, "other@example.com", "Unrelated team")
    client.cookies.clear()
    other = login(client, "other@example.com")
    cross = headers(other, first["organizations"][0]["id"])
    for path in [
        "dashboard",
        "agents",
        "crm/contacts",
        "knowledge/documents",
        "inbound/conversations",
        "messaging/messages",
        "campaigns",
        "organizations/current/invitations",
        "organizations/current/security-events",
    ]:
        assert client.get(f"/api/v1/{path}", headers=cross).status_code == 404, path
    assert (
        client.delete(
            f"/api/v1/auth/sessions/{private_session_id}", headers=headers(other)
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/organizations/current/members/{first['user']['id']}",
            headers=headers(other),
            json={"role": "admin", "is_active": True},
        ).status_code
        == 404
    )


def test_generic_registration_hashes_and_expired_session(client):
    register_and_verify(client, "account@example.com", "First")
    with patch("app.api.routes.auth.send_verification_email", AsyncMock()) as sender:
        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "email": "account@example.com",
                "full_name": "Another Person",
                "organization_name": "Another",
                "password": "AnotherPassword123!",
            },
        )
    assert duplicate.status_code == 201 and "Registration successful" in duplicate.json()["message"]
    sender.assert_not_called()
    session = login(client, "account@example.com")

    async def expire(db):
        user = await db.get(User, uuid.UUID(session["user"]["id"]))
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password("VerySecure123!", user.password_hash)
        stored = await db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert stored.token_hash == token_digest(client.cookies.get(settings.session_cookie_name))
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    db_run(expire)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_explicit_permissions_fail_closed():
    assert has_permission(MembershipRole.employee, "crm.read")
    assert not has_permission(MembershipRole.employee, "crm.manage")
    assert has_permission(MembershipRole.manager, "campaigns.manage")
    assert not has_permission(MembershipRole.manager, "campaigns.approve")
    assert not has_permission("unknown", "workspace.read")
    assert not has_permission(MembershipRole.admin, "future.finance.transfer")


def test_employee_inbox_is_limited_to_assignments(client):
    from tests.test_inbound import setup_site

    with patch("app.api.routes.inbound.check_rate_limit", AsyncMock()):
        owner_headers, owner, site = setup_site(client, "owner@example.com")
        root = f"/api/v1/public/inbound/{site['id']}"
        first = client.post(root + "/sessions").json()
        second = client.post(root + "/sessions").json()
    employee = add_member(client, owner)
    employee_cookie = client.cookies.get(settings.session_cookie_name)
    organization = owner_headers["X-Organization-ID"]
    client.cookies.clear()
    owner = login(client, "owner@example.com")
    assert (
        client.post(
            f"/api/v1/inbound/conversations/{first['conversation_id']}/assign",
            headers=headers(owner),
            json={"assigned_to": employee["user"]["id"], "status": "human"},
        ).status_code
        == 200
    )
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, employee_cookie, domain="testserver.local")
    employee_headers = headers(employee, organization)
    listed = client.get("/api/v1/inbound/conversations", headers=employee_headers)
    assert [item["id"] for item in listed.json()] == [first["conversation_id"]]
    assert (
        client.get(
            f"/api/v1/inbound/conversations/{second['conversation_id']}", headers=employee_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/inbound/conversations/{first['conversation_id']}", headers=employee_headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/inbound/conversations/{first['conversation_id']}/reply",
            headers=employee_headers,
            json={"message": "I can help."},
        ).status_code
        == 200
    )


def test_disabled_user_and_security_event_redaction(client):
    register_and_verify(client, "owner@example.com", "Main team")
    owner = login(client, "owner@example.com")
    events = client.get("/api/v1/organizations/current/security-events", headers=headers(owner))
    assert events.status_code == 200
    actions = {item["action"] for item in events.json()}
    assert {"registered", "email_verified", "signed_in"} <= actions
    assert "VerySecure123!" not in events.text
    assert owner["csrf_token"] not in events.text
    assert client.cookies.get(settings.session_cookie_name) not in events.text

    async def disable(db):
        user = await db.get(User, uuid.UUID(owner["user"]["id"]))
        user.is_active = False
        await db.commit()

    db_run(disable)
    assert client.get("/api/v1/auth/session").status_code == 401
    assert client.get("/api/v1/crm/contacts", headers=headers(owner)).status_code == 401


def test_authentication_rate_limit_uses_existing_shared_limiter(client, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "app_env", "production")
    limiter = AsyncMock(
        side_effect=HTTPException(429, "Too many requests", headers={"Retry-After": "60"})
    )
    with patch("app.core.inbound_rate.check_rate_limit", limiter):
        result = client.post(
            "/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong"}
        )
    assert result.status_code == 429 and result.headers["retry-after"] == "60"
    limiter.assert_awaited_once()


def test_manager_cannot_escalate_or_change_member_permissions(client):
    register_and_verify(client, "owner@example.com", "Main team")
    owner = login(client, "owner@example.com")
    manager = add_member(client, owner, "manager@example.com", "manager")
    auth = headers(manager, owner["organizations"][0]["id"])
    assert (
        client.post(
            "/api/v1/organizations/current/invitations",
            headers=auth,
            json={"email": "escalate@example.com", "role": "admin"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/organizations/current/members/{manager['user']['id']}",
            headers=auth,
            json={"role": "admin", "is_active": True},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/campaigns", headers=auth).status_code == 200


@pytest.mark.parametrize(
    "purpose,path", [("verify_email", "verify-email"), ("reset_password", "reset-password")]
)
def test_expired_email_tokens_and_invalid_request_fields(client, purpose, path):
    register_and_verify(client, "owner@example.com", "Main team")
    token = "synthetic-expired-token-with-enough-characters"

    async def add_expired(db):
        user = await db.scalar(select(User).where(User.email == "owner@example.com"))
        db.add(
            EmailToken(
                user_id=user.id,
                token_hash=token_digest(token),
                purpose=purpose,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await db.commit()

    db_run(add_expired)
    payload = {"token": token}
    if path == "reset-password":
        payload["password"] = "NewPassword123!"
    assert client.post(f"/api/v1/auth/{path}", json=payload).status_code == 400
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "other@example.com",
                "full_name": "  ",
                "organization_name": "Team",
                "password": "VerySecure123!",
            },
        ).status_code
        == 422
    )


def test_removed_sender_cannot_send_an_already_queued_message(client):
    from app.core.messaging_delivery import deliver_message
    from app.models.messaging import OutboundMessage

    register_and_verify(client, "owner@example.com", "Main team")
    owner = login(client, "owner@example.com")

    async def queue_and_revoke(db):
        item = OutboundMessage(
            organization_id=uuid.UUID(owner["organizations"][0]["id"]),
            created_by=uuid.UUID(owner["user"]["id"]),
            channel="email",
            recipient="test@example.com",
            body="Test",
            idempotency_key="revoked-sender",
        )
        db.add(item)
        member = await db.scalar(select(Membership).where(Membership.user_id == item.created_by))
        member.is_active = False
        await db.commit()
        return item.id, db.bind

    message_id, engine = db_run(queue_and_revoke)
    provider = AsyncMock()
    with (
        patch("app.core.messaging_delivery.create_async_engine", return_value=engine),
        patch("app.core.messaging_delivery.httpx.AsyncClient", provider),
    ):
        import asyncio

        asyncio.run(deliver_message(message_id))
    provider.assert_not_called()

    async def outcome(db):
        return (await db.get(OutboundMessage, message_id)).status

    assert db_run(outcome) == "failed"
