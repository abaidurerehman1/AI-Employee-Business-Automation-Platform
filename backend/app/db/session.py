from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

pool_options = (
    {}
    if settings.database_url.startswith("sqlite")
    else {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout,
        "connect_args": {"timeout": 5, "command_timeout": 30},
    }
)
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    hide_parameters=True,
    **pool_options,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
redis_client = Redis.from_url(
    settings.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
)


async def get_db():
    async with async_session_factory() as session:
        yield session


async def close_connections() -> None:
    await engine.dispose()
    await redis_client.aclose()
