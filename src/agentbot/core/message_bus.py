"""Simple in-memory asynchronous message bus."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, Optional, Set, Tuple

from .models import EventEnvelope, EventType


Subscriber = Callable[[EventEnvelope], Awaitable[None]]


@dataclass(slots=True, eq=False)
class _Subscription:
    queue: "asyncio.Queue[EventEnvelope]"
    session_filter: Optional[str]


class MessageBus:
    """Pub/sub bus with optional session filtering."""

    def __init__(self) -> None:
        self._topics: Dict[EventType, Set[_Subscription]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._closed = False

    async def publish(self, envelope: EventEnvelope) -> None:
        """Publish an event to subscribers."""
        if self._closed:
            raise RuntimeError("MessageBus is closed")

        async with self._lock:
            subscriptions = list(self._topics.get(envelope.type, set()))

        for subscription in subscriptions:
            if subscription.session_filter and subscription.session_filter != envelope.session_id:
                continue
            try:
                subscription.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # Backpressure: drop oldest to ensure newest availability event goes through.
                try:
                    subscription.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                subscription.queue.put_nowait(envelope)

    async def subscribe(
        self,
        event_type: EventType,
        *,
        session_id: Optional[str] = None,
        max_queue: int = 10,
    ) -> AsyncIterator[EventEnvelope]:
        """Subscribe to event stream, optionally filtered by session id."""
        if self._closed:
            raise RuntimeError("MessageBus is closed")

        queue: "asyncio.Queue[EventEnvelope]" = asyncio.Queue(max_queue)
        subscription = _Subscription(queue=queue, session_filter=session_id)
        async with self._lock:
            self._topics[event_type].add(subscription)

        try:
            while True:
                envelope = await queue.get()
                yield envelope
        finally:
            async with self._lock:
                self._topics[event_type].discard(subscription)

    async def close(self) -> None:
        """Stop accepting new events and unblock subscribers."""
        self._closed = True
        async with self._lock:
            topics = list(self._topics.items())
            self._topics.clear()
        for event_type, subscriptions in topics:
            sentinel = EventEnvelope(
                type=event_type,
                session_id="*",
                payload={"message": "MessageBus closed", "__bus_closed__": True},
            )
            for subscription in subscriptions:
                try:
                    subscription.queue.put_nowait(sentinel)
                except asyncio.QueueFull:
                    try:
                        subscription.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    subscription.queue.put_nowait(sentinel)
