import redis as redis_sync

from app.core import rate_limit
from app.core.config import get_settings


async def test_rate_limit_key_always_gets_a_ttl() -> None:
    key = "rl:test:ttl"
    assert await rate_limit.hit(key, limit=3, window_seconds=60)
    with redis_sync.from_url(get_settings().redis_url) as r:
        ttl = r.ttl(key)
    assert 0 < ttl <= 60


async def test_window_starts_at_first_hit_and_is_not_extended() -> None:
    key = "rl:test:window"
    await rate_limit.hit(key, limit=10, window_seconds=60)
    with redis_sync.from_url(get_settings().redis_url) as r:
        r.expire(key, 5)  # simulate time passing
    await rate_limit.hit(key, limit=10, window_seconds=60)  # must not reset to 60
    with redis_sync.from_url(get_settings().redis_url) as r:
        assert r.ttl(key) <= 5


async def test_limit_is_enforced() -> None:
    key = "rl:test:limit"
    results = [await rate_limit.hit(key, limit=3, window_seconds=60) for _ in range(5)]
    assert results == [True, True, True, False, False]
