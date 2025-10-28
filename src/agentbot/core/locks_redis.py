"""Redis-based distributed lock using SET NX PX semantics."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from redis.asyncio import Redis

from .locks import AsyncLock, LockManager


class _RedisLock:
    def __init__(self, redis: Redis, key: str, ttl_ms: int) -> None:
        self._redis = redis
        self._key = f"lock:{key}"
        self._ttl_ms = ttl_ms
        self._token = str(uuid.uuid4())
        self._acquired = False

    async def __aenter__(self) -> bool:
        self._acquired = bool(
            await self._redis.set(self._key, self._token, px=self._ttl_ms, nx=True)
        )
        return self._acquired

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if not self._acquired:
            return
        # release only if token matches
        lua = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        try:
            await self._redis.eval(lua, 1, self._key, self._token)
        finally:
            self._acquired = False


class RedisLockManager(LockManager):
    def __init__(self, url: Optional[str] = None) -> None:
        self._redis = Redis.from_url(url or os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    def lock(self, key: str, ttl_ms: int = 30000) -> AsyncLock:
        return _RedisLock(self._redis, key, ttl_ms)


