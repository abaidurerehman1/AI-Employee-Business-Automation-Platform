from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def register_and_verify(
    client: TestClient,
    email: str,
    organization: str,
    password: str = "VerySecure123!",
) -> None:
    email_mock = AsyncMock()
    with patch("app.api.routes.auth.send_verification_email", email_mock):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "full_name": "Test User",
                "password": password,
                "organization_name": organization,
            },
        )
    assert response.status_code == 201, response.text
    token = email_mock.await_args.args[1]
    response = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 200, response.text


def login(client: TestClient, email: str, password: str = "VerySecure123!") -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_registration_verification_login_and_logout(client: TestClient) -> None:
    email_mock = AsyncMock()
    with patch("app.api.routes.auth.send_verification_email", email_mock):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "full_name": "Owner Name",
                "password": "VerySecure123!",
                "organization_name": "Owner Company",
            },
        )
    assert response.status_code == 201
    token = email_mock.await_args.args[1]

    resend_mock = AsyncMock()
    with patch("app.api.routes.auth.send_verification_email", resend_mock):
        resent = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "owner@example.com"},
        )
    assert resent.status_code == 200
    token = resend_mock.await_args.args[1]

    blocked_login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "VerySecure123!"},
    )
    assert blocked_login.status_code == 403

    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    session = login(client, "owner@example.com")
    assert session["organizations"][0]["role"] == "admin"
    assert "ai_employee_session" in client.cookies

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_password_reset_is_one_time_and_revokes_sessions(client: TestClient) -> None:
    register_and_verify(client, "reset@example.com", "Reset Company")
    login(client, "reset@example.com")

    reset_mock = AsyncMock()
    with patch("app.api.routes.auth.send_reset_email", reset_mock):
        response = client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
    assert response.status_code == 200
    token = reset_mock.await_args.args[1]

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "NewSecurePassword123!"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "AnotherSecure123!"},
        ).status_code
        == 400
    )
    login(client, "reset@example.com", "NewSecurePassword123!")


def test_invitation_permissions_and_cross_tenant_isolation(client: TestClient) -> None:
    register_and_verify(client, "admin@example.com", "Admin Organization")
    admin_session = login(client, "admin@example.com")
    admin_org = admin_session["organizations"][0]["id"]

    invitation_mock = AsyncMock()
    with patch("app.api.routes.organizations.send_invitation_email", invitation_mock):
        response = client.post(
            "/api/v1/organizations/current/invitations",
            headers={
                "X-Organization-ID": admin_org,
                "X-CSRF-Token": admin_session["csrf_token"],
            },
            json={"email": "employee@example.com", "role": "employee"},
        )
    assert response.status_code == 201, response.text
    invitation_token = invitation_mock.await_args.args[2]

    client.cookies.clear()
    register_and_verify(client, "employee@example.com", "Employee Personal Org")
    employee_session = login(client, "employee@example.com")
    employee_own_org = employee_session["organizations"][0]["id"]
    response = client.post(
        "/api/v1/organizations/invitations/accept",
        headers={"X-CSRF-Token": employee_session["csrf_token"]},
        json={"token": invitation_token},
    )
    assert response.status_code == 200, response.text

    refreshed = client.get("/api/v1/auth/session").json()
    employee_admin_org = next(org for org in refreshed["organizations"] if org["id"] == admin_org)
    assert employee_admin_org["role"] == "employee"

    forbidden = client.post(
        "/api/v1/organizations/current/invitations",
        headers={
            "X-Organization-ID": admin_org,
            "X-CSRF-Token": refreshed["csrf_token"],
        },
        json={"email": "another@example.com", "role": "employee"},
    )
    assert forbidden.status_code == 403

    client.cookies.clear()
    admin_session = login(client, "admin@example.com")
    cross_tenant = client.get(
        "/api/v1/organizations/current/members",
        headers={"X-Organization-ID": employee_own_org},
    )
    assert cross_tenant.status_code == 404

    own_members = client.get(
        "/api/v1/organizations/current/members",
        headers={"X-Organization-ID": admin_org},
    )
    assert own_members.status_code == 200
    assert {member["email"] for member in own_members.json()} == {
        "admin@example.com",
        "employee@example.com",
    }
