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
from agentbot.core.planner import AgentPlanner, SessionState
from agentbot.data.session_store import SessionRecord, SessionStore


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
    config = AgentConfig(session_id=record.session_id, user_id=record.user_id, poll_interval_seconds=5)

    planner = AgentPlanner()
    monitor = MonitorAgent(
        config,
        message_bus=bus,
        session_record=record,
        provider=DummyAvail(),
        planner=planner,
    )
    booking = BookingAgent(
        config,
        message_bus=bus,
        session_record=record,
        provider=DummyBook(),
        planner=planner,
    )

    await booking.start()
    await monitor.start()

    # Wait for booking result event
    async def wait_result():
        async for e in bus.subscribe(EventType.BOOKING_RESULT, session_id=record.session_id):
            return e

    envelope = await asyncio.wait_for(wait_result(), timeout=5)
    assert envelope.payload.get("success") is True
    assert planner.get_state(record.session_id) is SessionState.BOOKED

    await bus.close()
    await booking.stop()
    await monitor.stop()


@pytest.mark.asyncio
async def test_session_store_encryption(tmp_path):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    path = tmp_path / "sessions.enc"
    store = SessionStore(path, encryption_key=key)
    record = SessionRecord(session_id="sess", user_id="user", email="test@example.com")
    await store.upsert(record)

    raw = path.read_bytes()
    assert b"test@example.com" not in raw  # ciphertext should hide plain data

    restored = SessionStore(path, encryption_key=key)
    sessions = await restored.list_sessions()
    assert sessions[0].email == "test@example.com"
