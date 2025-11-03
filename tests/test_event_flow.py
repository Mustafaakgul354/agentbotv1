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
    session_record = SessionRecord(
        session_id="s-1",
        user_id="u-1",
        email="e@example.com",
    )
    agent_config = AgentConfig(session_id=session_record.session_id, user_id=session_record.user_id, poll_interval_seconds=5)

    monitor = MonitorAgent(agent_config, message_bus=bus, session_record=session_record, provider=DummyAvail())
    booking = BookingAgent(agent_config, message_bus=bus, session_record=session_record, provider=DummyBook())

    await monitor.start()
    await booking.start()
    
    # Give agents a moment to fully start and subscribe
    await asyncio.sleep(0.1)

    # Wait for booking result event
    async def wait_result():
        async for event_envelope in bus.subscribe(EventType.BOOKING_RESULT, session_id=session_record.session_id):
            return event_envelope

    result_envelope = await asyncio.wait_for(wait_result(), timeout=10)
    assert result_envelope.payload.get("success") is True

    await monitor.stop()
    await booking.stop()

