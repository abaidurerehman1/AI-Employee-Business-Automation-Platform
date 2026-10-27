from unittest.mock import AsyncMock, MagicMock, patch

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
