import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
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
async def health_check(response: Response) -> HealthResponse:
    database_status: Literal["healthy", "unhealthy"] = "unhealthy"
    redis_status: Literal["healthy", "unhealthy"] = "unhealthy"

    try:

        async def database_ping():
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        await asyncio.wait_for(database_ping(), timeout=settings.health_timeout_seconds)
        database_status = "healthy"
    except Exception:
        pass

    try:
        if await asyncio.wait_for(redis_client.ping(), timeout=settings.health_timeout_seconds):
            redis_status = "healthy"
    except Exception:
        pass

    overall = (
        "healthy" if database_status == "healthy" and redis_status == "healthy" else "degraded"
    )
    if overall == "degraded":
        response.status_code = 503
    return HealthResponse(
        status=overall,
        api=ServiceHealth(status="healthy"),
        database=ServiceHealth(status=database_status),
        redis=ServiceHealth(status=redis_status),
    )


@router.get("/live")
async def liveness():
    return {"status": "alive"}


@lru_cache
def migration_heads():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def check_schema():
    async with engine.connect() as connection:
        versions = set(
            (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars()
        )
        if versions != migration_heads():
            return False
        if connection.dialect.name == "postgresql":
            return bool(
                await connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
                )
            )
        return True


async def check_temporal():
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
    from temporalio.client import Client

    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
        api_key=settings.temporal_api_key or None,
    )
    await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=settings.temporal_namespace)
    )
    return True


@router.get("/ready")
async def readiness(response: Response):
    async def probe(check):
        try:
            return (
                "healthy"
                if await asyncio.wait_for(check(), timeout=settings.health_timeout_seconds)
                else "unhealthy"
            )
        except Exception:
            return "unhealthy"

    schema, redis, temporal = await asyncio.gather(
        probe(check_schema), probe(redis_client.ping), probe(check_temporal)
    )
    healthy = all(state == "healthy" for state in [schema, redis, temporal])
    response.status_code = 200 if healthy else 503
    return {
        "status": "ready" if healthy else "not_ready",
        "database_schema": schema,
        "redis": redis,
        "temporal": temporal,
    }
