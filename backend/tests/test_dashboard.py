from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tests.test_auth import login, register_and_verify


def test_dashboard_is_tenant_scoped_and_role_aware(client: TestClient) -> None:
    register_and_verify(client, "owner@example.com", "First")
    owner = login(client, "owner@example.com")
    first_id = owner["organizations"][0]["id"]
    headers = {"X-Organization-ID": first_id, "X-CSRF-Token": owner["csrf_token"]}
    with patch("app.api.routes.organizations.send_invitation_email", new=AsyncMock()):
        assert (
            client.post(
                "/api/v1/organizations/current/invitations",
                headers=headers,
                json={"email": "invite@example.com", "role": "employee"},
            ).status_code
            == 201
        )
    result = client.get("/api/v1/dashboard", headers=headers)
    assert result.status_code == 200
    assert result.json()["member_count"] == 1
    assert result.json()["pending_invitation_count"] == 1
    assert len(result.json()["notifications"]) == 1

    client.cookies.clear()
    register_and_verify(client, "other@example.com", "Second")
    login(client, "other@example.com")
    assert client.get("/api/v1/dashboard", headers=headers).status_code == 404
    assert client.get("/api/v1/dashboard/notifications", headers=headers).status_code == 404
    assert client.get("/api/v1/dashboard/search?q=owner", headers=headers).status_code == 404


def test_employee_cannot_see_invitation_notifications(client: TestClient) -> None:
    register_and_verify(client, "admin@example.com", "Team")
    admin = login(client, "admin@example.com")
    org_id = admin["organizations"][0]["id"]
    headers = {"X-Organization-ID": org_id, "X-CSRF-Token": admin["csrf_token"]}
    email = AsyncMock()
    with patch("app.api.routes.organizations.send_invitation_email", email):
        assert (
            client.post(
                "/api/v1/organizations/current/invitations",
                headers=headers,
                json={"email": "worker@example.com", "role": "employee"},
            ).status_code
            == 201
        )
    token = email.await_args.args[2]
    client.cookies.clear()
    register_and_verify(client, "worker@example.com", "Worker workspace")
    worker = login(client, "worker@example.com")
    assert (
        client.post(
            "/api/v1/organizations/invitations/accept",
            headers={"X-CSRF-Token": worker["csrf_token"]},
            json={"token": token},
        ).status_code
        == 200
    )
    with patch("app.api.routes.organizations.send_invitation_email", new=AsyncMock()):
        client.cookies.clear()
        admin = login(client, "admin@example.com")
        dashboard = client.get("/api/v1/dashboard", headers={"X-Organization-ID": org_id})
        assert dashboard.json()["member_count"] == 2
        assert dashboard.json()["pending_invitation_count"] == 0
        client.post(
            "/api/v1/organizations/current/invitations",
            headers={"X-Organization-ID": org_id, "X-CSRF-Token": admin["csrf_token"]},
            json={"email": "private@example.com", "role": "employee"},
        )
    client.cookies.clear()
    login(client, "worker@example.com")
    response = client.get("/api/v1/dashboard", headers={"X-Organization-ID": org_id})
    assert response.status_code == 200
    assert response.json()["pending_invitation_count"] is None
    assert response.json()["notifications"] == []
    assert "private@example.com" not in response.text


def test_dashboard_metrics_dates_currency_and_search_are_real_and_tenant_scoped(client):
    import uuid
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.auth import Organization
    from app.models.crm import Contact, Deal, Lead
    from app.models.messaging import MessageEvent
    from tests.test_campaigns import db_run

    register_and_verify(client, "owner@example.com", "First")
    owner = login(client, "owner@example.com")
    org = uuid.UUID(owner["organizations"][0]["id"])
    headers = {"X-Organization-ID": str(org), "X-CSRF-Token": owner["csrf_token"]}
    register_and_verify(client, "other@example.com", "Foreign")

    async def seed(db):
        other = await db.scalar(select(Organization).where(Organization.name == "Foreign"))
        db.add_all(
            [
                MessageEvent(
                    organization_id=org, provider="test", event_id="local-reply", kind="reply"
                ),
                MessageEvent(
                    organization_id=other.id,
                    provider="test",
                    event_id="foreign-reply",
                    kind="reply",
                ),
                MessageEvent(
                    organization_id=org, provider="test", event_id="delivered", kind="delivered"
                ),
            ]
        )
        db.add_all(
            [
                Contact(organization_id=org, name="Sara local", email="local@example.com"),
                Contact(organization_id=other.id, name="Sara secret", email="secret@example.com"),
                Lead(organization_id=org, title="Current lead", stage="qualified"),
                Lead(
                    organization_id=org,
                    title="Old lead",
                    stage="new",
                    created_at=datetime.now(UTC) - timedelta(days=40),
                ),
                Lead(organization_id=other.id, title="Private lead", stage="new"),
                Deal(
                    organization_id=org,
                    title="USD deal",
                    currency="USD",
                    amount_minor=12345,
                    stage="open",
                ),
                Deal(
                    organization_id=org,
                    title="PKR deal",
                    currency="PKR",
                    amount_minor=100000,
                    stage="negotiation",
                ),
                Deal(
                    organization_id=org,
                    title="Won deal",
                    currency="USD",
                    amount_minor=50000,
                    stage="won",
                ),
                Deal(
                    organization_id=other.id,
                    title="Foreign deal",
                    currency="USD",
                    amount_minor=999999,
                    stage="open",
                ),
            ]
        )
        await db.commit()

    db_run(seed)
    data = client.get("/api/v1/dashboard?days=7", headers=headers).json()
    assert data["metrics"]["contacts"] == 1 and data["metrics"]["leads"] == 1
    assert data["metrics"]["deals"] == 3
    assert data["metrics"]["recorded_replies"] == 1
    assert len(data["lead_trend"]) == 7 and sum(row["count"] for row in data["lead_trend"]) == 1
    assert data["lead_stages"] == [{"stage": "qualified", "count": 1}]
    assert {row["currency"]: row["amount_minor"] for row in data["pipeline"]} == {
        "USD": 12345,
        "PKR": 100000,
    }
    assert "Private lead" not in str(data) and "Foreign deal" not in str(data)
    assert client.get("/api/v1/dashboard?days=90", headers=headers).json()["metrics"]["leads"] == 2
    results = client.get("/api/v1/dashboard/search?q=Sara", headers=headers).json()["items"]
    assert [row["label"] for row in results] == ["Sara local"]
    assert client.get("/api/v1/dashboard/search?q=%25%25", headers=headers).json()["items"] == []
    assert client.get("/api/v1/dashboard?days=1000", headers=headers).status_code == 422


def test_notification_read_receipts_pagination_idempotency_and_role_checks(client):
    from tests.test_identity_management import add_member, headers, invite

    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    org = owner["organizations"][0]["id"]
    invite(client, owner, "pending@example.com")
    admin = add_member(client, owner, "admin@example.com", "admin")
    client.cookies.clear()
    owner = login(client, "owner@example.com")
    response = client.get("/api/v1/dashboard/notifications?page_size=1", headers=headers(owner))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and response.json()["unread_count"] == 1
    notification = response.json()["items"][0]
    path = "/api/v1/dashboard/notifications/" + notification["id"] + "/read"
    assert (
        client.put(path, json={"read": True}, headers={"X-Organization-ID": org}).status_code == 403
    )
    for _ in range(2):
        assert client.put(path, json={"read": True}, headers=headers(owner)).status_code == 204
    assert (
        client.get("/api/v1/dashboard/notifications?state=unread", headers=headers(owner)).json()[
            "total"
        ]
        == 0
    )
    assert client.get("/api/v1/dashboard", headers=headers(owner)).json()["unread_count"] == 0
    client.cookies.clear()
    admin = login(client, "admin@example.com")
    assert (
        client.get("/api/v1/dashboard/notifications", headers=headers(admin, org)).json()[
            "unread_count"
        ]
        == 1
    )
    assert client.put(path, json={"read": False}, headers=headers(admin)).status_code == 404
    assert (
        client.put(
            "/api/v1/dashboard/notifications/foreign-secret/read",
            json={"read": True},
            headers=headers(admin, org),
        ).status_code
        == 404
    )


def test_layout_is_organization_shared_admin_only_and_rejects_unknown_modules(client):
    from tests.test_identity_management import add_member, headers

    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    org = owner["organizations"][0]["id"]
    layout = {
        "industry": "clinic",
        "widgets": ["metrics", "activity"],
        "visible_modules": ["crm", "inbound"],
    }
    assert (
        client.put(
            "/api/v1/dashboard/configuration", headers=headers(owner), json=layout
        ).status_code
        == 200
    )
    assert client.get("/api/v1/dashboard", headers=headers(owner)).json()["configuration"] == layout
    assert (
        client.put(
            "/api/v1/dashboard/configuration",
            headers=headers(owner),
            json={**layout, "visible_modules": ["finance"]},
        ).status_code
        == 422
    )
    employee = add_member(client, owner)
    own_headers = headers(employee, org)
    assert client.get("/api/v1/dashboard", headers=own_headers).json()["configuration"] == layout
    assert (
        client.put("/api/v1/dashboard/configuration", headers=own_headers, json=layout).status_code
        == 403
    )
    assert (
        "messages_sent"
        not in client.get("/api/v1/dashboard", headers=own_headers).json()["metrics"]
    )


def test_disabled_members_and_revoked_invitations_are_not_pending(client):
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.auth import Invitation, Membership
    from tests.test_campaigns import db_run
    from tests.test_identity_management import add_member, headers, invite

    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    add_member(client, owner)
    client.cookies.clear()
    owner = login(client, "owner@example.com")
    invitation, _ = invite(client, owner, "pending@example.com")

    async def disable(db):
        rows = (
            await db.scalars(
                select(Membership).where(
                    Membership.organization_id == uuid.UUID(owner["organizations"][0]["id"]),
                    Membership.user_id != uuid.UUID(owner["user"]["id"]),
                )
            )
        ).all()
        for row in rows:
            row.is_active = False
        item = await db.get(Invitation, uuid.UUID(invitation["id"]))
        item.revoked_at = datetime.now(UTC)
        await db.commit()

    db_run(disable)
    data = client.get("/api/v1/dashboard", headers=headers(owner)).json()
    assert data["member_count"] == 1 and data["pending_invitation_count"] == 0
    assert not data["notifications"]


def test_notification_pagination_is_counted_before_limiting(client):
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.core.security import token_digest
    from app.models.auth import Invitation, MembershipRole
    from tests.test_campaigns import db_run
    from tests.test_identity_management import headers

    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")

    async def seed(db):
        for index in range(25):
            db.add(
                Invitation(
                    organization_id=uuid.UUID(owner["organizations"][0]["id"]),
                    email=f"invite-{index}@example.com",
                    role=MembershipRole.employee,
                    invited_by_user_id=uuid.UUID(owner["user"]["id"]),
                    token_hash=token_digest(str(uuid.uuid4())),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        await db.commit()

    db_run(seed)
    first = client.get(
        "/api/v1/dashboard/notifications?page=1&page_size=20", headers=headers(owner)
    ).json()
    second = client.get(
        "/api/v1/dashboard/notifications?page=2&page_size=20", headers=headers(owner)
    ).json()
    assert first["total"] == 25 and first["unread_count"] == 25
    assert len(first["items"]) == 20 and len(second["items"]) == 5
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}


def test_employee_activity_and_alerts_cannot_expose_other_users_tools_or_inbox(client):
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.models.agent import Agent, AgentToolRequest, AgentVersion
    from app.models.inbound import InboundSite, VisitorConversation
    from tests.test_campaigns import db_run
    from tests.test_identity_management import add_member, headers

    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    worker = add_member(client, owner)
    org_id = uuid.UUID(owner["organizations"][0]["id"])
    worker_id = uuid.UUID(worker["user"]["id"])
    owner_id = uuid.UUID(owner["user"]["id"])

    async def seed(db):
        agent = Agent(organization_id=org_id, name="Sales", status="draft")
        db.add(agent)
        await db.flush()
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            role="Sales",
            instructions="Help",
            tone="Professional",
            language="English",
            model="test",
            tools=[],
            approval_rules={},
        )
        db.add(version)
        await db.flush()
        db.add_all(
            [
                AgentToolRequest(
                    organization_id=org_id,
                    agent_id=agent.id,
                    version_id=version.id,
                    requested_by=owner_id,
                    tool_name="private_owner_action",
                    arguments={},
                    status="pending",
                ),
                AgentToolRequest(
                    organization_id=org_id,
                    agent_id=agent.id,
                    version_id=version.id,
                    requested_by=worker_id,
                    tool_name="worker_action",
                    arguments={},
                    status="failed",
                ),
            ]
        )
        site = InboundSite(
            organization_id=org_id, agent_id=agent.id, name="Test", webhook_secret="synthetic"
        )
        db.add(site)
        await db.flush()
        for user_id, name in [(owner_id, "Private visitor"), (worker_id, "Assigned visitor")]:
            db.add(
                VisitorConversation(
                    organization_id=org_id,
                    site_id=site.id,
                    token_hash=uuid.uuid4().hex,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    visitor_name=name,
                    status="human",
                    assigned_to=user_id,
                    context={},
                )
            )
        await db.commit()

    db_run(seed)
    response = client.get("/api/v1/dashboard", headers=headers(worker, str(org_id)))
    assert response.status_code == 200, response.text
    assert response.json()["metrics"]["human_conversations"] == 1
    assert "private_owner_action" not in response.text and "Private visitor" not in response.text
    assert "worker_action" in response.text and "Assigned visitor" in response.text
