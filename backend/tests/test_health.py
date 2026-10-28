from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_root() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_health_reports_dependencies() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock()
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = connection
    mock_engine = MagicMock()
    mock_engine.connect.return_value = context_manager

    with (
        patch("app.api.routes.health.engine", mock_engine),
        patch("app.api.routes.health.redis_client.ping", new=AsyncMock(return_value=True)),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "api": {"status": "healthy"},
        "database": {"status": "healthy"},
        "redis": {"status": "healthy"},
    }


def test_dependency_failure_returns_503_but_liveness_remains_available():
    broken_engine = MagicMock()
    broken_engine.connect.side_effect = RuntimeError("private database details")
    with (
        patch("app.api.routes.health.engine", broken_engine),
        patch(
            "app.api.routes.health.redis_client.ping",
            AsyncMock(side_effect=RuntimeError("private redis details")),
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert "private" not in response.text
        assert client.get("/api/v1/live").json() == {"status": "alive"}


@pytest.mark.parametrize(
    "schema,redis,temporal",
    [(True, True, True), (False, True, True), (True, False, True), (True, True, False)],
)
def test_readiness_checks_schema_and_workflow_service(schema, redis, temporal):
    with (
        patch("app.api.routes.health.check_schema", AsyncMock(return_value=schema)),
        patch("app.api.routes.health.redis_client.ping", AsyncMock(return_value=redis)),
        patch("app.api.routes.health.check_temporal", AsyncMock(return_value=temporal)),
        TestClient(app) as client,
    ):
        assert client.get("/api/v1/ready").status_code == (
            200 if schema and redis and temporal else 503
        )


def test_security_headers_cors_and_validation_redaction():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register", json={"email": "invalid", "password": "private-test-password"}
        )
        assert response.status_code == 422
        assert "private-test-password" not in response.text
        assert response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400
        allowed = client.options(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        denied = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in denied.headers


def test_unexpected_errors_remain_generic_and_readable_across_cors():
    from fastapi.routing import APIRoute

    def failure():
        raise RuntimeError("private-database-credential")

    route = APIRoute("/_foundation_failure", failure, methods=["GET"])
    app.router.routes.append(route)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/_foundation_failure", headers={"Origin": "http://localhost:5173"}
            )
            assert response.status_code == 500
            assert "private-database-credential" not in response.text
            assert response.json()["request_id"] == response.headers["x-request-id"]
            assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    finally:
        app.router.routes.remove(route)


def test_production_authentication_reuses_rate_limit_and_fails_closed(monkeypatch):
    from fastapi import HTTPException
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    with (
        patch(
            "app.core.inbound_rate.check_rate_limit",
            AsyncMock(side_effect=HTTPException(429, "Too many requests")),
        ) as limiter,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/v1/auth/login", json={"email": "test@example.com", "password": "Synthetic123!"}
        )
        assert response.status_code == 429
        assert limiter.await_args.args[1] == "authentication"
