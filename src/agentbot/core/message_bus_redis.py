"""Redis-backed message bus using Streams and consumer groups."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

from redis.asyncio import Redis

from .models import EventEnvelope, EventType


class RedisMessageBus:
    def __init__(self, url: str, *, stream: str = "agentbot.events") -> None:
        self._redis = Redis.from_url(url, decode_responses=True)
        self._stream = stream
        self._closed = False

    async def publish(self, envelope: EventEnvelope) -> None:
        if self._closed:
            raise RuntimeError("RedisMessageBus is closed")
        payload = json.dumps(envelope.model_dump(mode="json"))
        await self._redis.xadd(self._stream, {"event": payload})

    async def subscribe(
        self, event_type: EventType, *, session_id: Optional[str] = None, max_queue: int = 10
    ) -> AsyncIterator[EventEnvelope]:
        group = f"g:{event_type}"
        consumer = f"c:{session_id or '*'}:{id(self)}"
        try:
            await self._redis.xgroup_create(self._stream, group, id="$", mkstream=True)
        except Exception:
            pass

        while not self._closed:
            res = await self._redis.xreadgroup(group, consumer, {self._stream: ">"}, count=10, block=5000)
            if not res:
                continue
            _, entries = res[0]
            for entry_id, fields in entries:
                try:
                    raw = fields.get("event")
                    if not raw:
                        await self._redis.xack(self._stream, group, entry_id)
                        continue
                    envelope = EventEnvelope.model_validate_json(raw)
                    if envelope.type != event_type:
                        await self._redis.xack(self._stream, group, entry_id)
                        continue
                    if session_id and envelope.session_id != session_id:
                        await self._redis.xack(self._stream, group, entry_id)
                        continue
                    yield envelope
                finally:
                    await self._redis.xack(self._stream, group, entry_id)

    async def close(self) -> None:
        self._closed = True
        await self._redis.aclose()


