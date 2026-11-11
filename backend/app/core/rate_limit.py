"""Fixed-window rate limiting backed by Valkey (Redis protocol).

Simple and good enough for login protection: `INCR key` + `EXPIRE` on first hit.
Sliding windows for the chat widget come in Phase 7/8.
"""

from functools import lru_cache

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache
def get_redis() -> "redis.Redis":
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Record one hit. Returns True if the caller is still within the limit.

    If Valkey is unreachable we *allow* the request (fail-open) and log loudly:
    an outage of the limiter must not lock every user out of the dashboard.
    """
    try:
        # INCR and EXPIRE in one atomic MULTI/EXEC. `nx=True` sets the expiry only
        # when the key has none, so the window starts at the first hit and a key
        # can never be left without a TTL (which would lock the user out forever).
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = await pipe.execute()
        return int(count) <= limit
    except redis.RedisError as exc:
        log.warning("rate_limiter_unavailable", error=str(exc), key=key)
        return True


async def reset(key: str) -> None:
    try:
        await get_redis().delete(key)
    except redis.RedisError:
        pass
