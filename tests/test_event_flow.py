from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from agentbot.agents.booking import BookingAgent, BookingProvider
from agentbot.agents.monitor import AvailabilityProvider, MonitorAgent
from agentbot.core.message_bus import MessageBus
from agentbot.core.models import (
    AgentConfig,
    AppointmentAvailability,
    AppointmentBookingRequest,
    AppointmentBookingResult,
    EventType,
)
from agentbot.data.session_store import SessionRecord


class DummyAvail(AvailabilityProvider):
    async def ensure_login(self, session: SessionRecord) -> None:  # pragma: no cover - trivial
        return None

    def __init__(self) -> None:
        self._sent = False

    async def check(self, session: SessionRecord):
        if self._sent:
            return []
        self._sent = True
        return [
            AppointmentAvailability(
                session_id=session.session_id,
                slot_id="slot-1",
                slot_time=dt.datetime.now(dt.timezone.utc),
            )
        ]


class DummyBook(BookingProvider):
    async def book(self, request: AppointmentBookingRequest, session: SessionRecord) -> AppointmentBookingResult:
        return AppointmentBookingResult(session_id=session.session_id, success=True, slot=request.slot)


@pytest.mark.asyncio
async def test_monitor_to_booking_flow():
    bus = MessageBus()
    record = SessionRecord(
        session_id="s-1",
        user_id="u-1",
        email="e@example.com",
    )
    config = AgentConfig(session_id=record.session_id, user_id=record.user_id, poll_interval_seconds=1)

    monitor = MonitorAgent(config, message_bus=bus, session_record=record, provider=DummyAvail())
    booking = BookingAgent(config, message_bus=bus, session_record=record, provider=DummyBook())

    await monitor.start()
    await booking.start()

    # Wait for booking result event
    async def wait_result():
        async for e in bus.subscribe(EventType.BOOKING_RESULT, session_id=record.session_id):
            return e

    envelope = await asyncio.wait_for(wait_result(), timeout=5)
    assert envelope.payload.get("success") is True

    await monitor.stop()
    await booking.stop()

