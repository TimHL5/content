"""Redis clients. Workers use the sync client; the SSE endpoint uses the async one."""

from functools import lru_cache

import redis
import redis.asyncio as aioredis

from stylecut.settings import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=5,
    )


def new_async_redis() -> aioredis.Redis:
    """A fresh async client. Callers own it and must `aclose()` it."""
    return aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
