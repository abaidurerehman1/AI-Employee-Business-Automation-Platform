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
        dashboard = client.get(
            "/api/v1/dashboard", headers={"X-Organization-ID": org_id}
        )
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
