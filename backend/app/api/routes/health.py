from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.db.session import engine, redis_client

router = APIRouter(tags=["health"])


class ServiceHealth(BaseModel):
    status: Literal["healthy", "unhealthy"]


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    api: ServiceHealth
    database: ServiceHealth
    redis: ServiceHealth


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    database_status: Literal["healthy", "unhealthy"] = "unhealthy"
    redis_status: Literal["healthy", "unhealthy"] = "unhealthy"

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        database_status = "healthy"
    except Exception:
        pass

    try:
        if await redis_client.ping():
            redis_status = "healthy"
    except Exception:
        pass

    overall = (
        "healthy" if database_status == "healthy" and redis_status == "healthy" else "degraded"
    )
    return HealthResponse(
        status=overall,
        api=ServiceHealth(status="healthy"),
        database=ServiceHealth(status=database_status),
        redis=ServiceHealth(status=redis_status),
    )
