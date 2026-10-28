"""Isolated infrastructure checks: fresh database migration and Redis roundtrip."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_FOUNDATION") != "1", reason="Requires local PostgreSQL and Redis"
)
def test_fresh_database_migrations_and_redis():
    database_name = f"foundation_test_{uuid.uuid4().hex}"
    url = make_url(settings.database_url)
    sandbox = url.set(database=database_name).render_as_string(hide_password=False)

    async def database_command(statement):
        engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                await connection.execute(text(statement))
        finally:
            await engine.dispose()

    # The identifier is generated here, never supplied by a request or environment.
    assert (
        database_name.startswith("foundation_test_")
        and database_name.removeprefix("foundation_test_").isalnum()
    )
    asyncio.run(database_command(f'CREATE DATABASE "{database_name}"'))
    try:
        env = {**os.environ, "DATABASE_URL": sandbox}
        directory = Path(__file__).resolve().parents[1]
        for command in [["upgrade", "head"], ["check"], ["upgrade", "head"]]:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *command],
                env=env,
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert result.returncode == 0, result.stderr + result.stdout

        async def infrastructure():
            engine = create_async_engine(sandbox)
            redis = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
            key = f"foundation-test:{uuid.uuid4()}"
            try:
                async with engine.connect() as connection:
                    assert await connection.scalar(text("SELECT 1")) == 1
                    assert await connection.scalar(
                        text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                    )
                    assert (
                        await connection.scalar(text("SELECT version_num FROM alembic_version"))
                        == "20261028_0016"
                    )
                assert await redis.ping()
                await redis.set(key, b"ready", ex=30)
                assert await redis.get(key) == b"ready"
            finally:
                await redis.delete(key)
                await redis.aclose()
                await engine.dispose()

        asyncio.run(infrastructure())
    finally:
        asyncio.run(database_command(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
