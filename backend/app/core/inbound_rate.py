import hashlib
from fastapi import HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from app.core.config import settings


async def check_rate_limit(request: Request, site_id: str, action: str, limit: int = 30) -> None:
    # Never trust forwarded IP headers unless a trusted proxy sanitizes them.
    address = request.client.host if request.client else "unknown"
    key = f"inbound:{site_id}:{action}:{hashlib.sha256(address.encode()).hexdigest()}"
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 60, nx=True)
            count, _ = await pipe.execute()
        if count > limit:
            raise HTTPException(429, "Too many requests. Please try again shortly.", headers={"Retry-After": "60"})
    except RedisError as exc:
        raise HTTPException(503, "Public service is temporarily unavailable") from exc
    finally:
        await redis.aclose()
