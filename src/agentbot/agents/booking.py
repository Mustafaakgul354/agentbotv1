"""Booking agent implementation."""

from __future__ import annotations

from typing import Optional, Protocol

from agentbot.agents.base import BaseAgent
from agentbot.core.message_bus import MessageBus
from agentbot.core.locks import LockManager
from agentbot.core.models import (
    AgentConfig,
    AppointmentAvailability,
    AppointmentBookingRequest,
    AppointmentBookingResult,
    EventEnvelope,
    EventType,
)
from agentbot.core.planner import AgentPlanner
from agentbot.data.session_store import SessionRecord
from agentbot.services.audit_logger import AuditLogger


class BookingProvider(Protocol):
    """Provider encapsulating booking flow interactions."""

    async def book(self, request: AppointmentBookingRequest, session: SessionRecord) -> AppointmentBookingResult:
        ...


class BookingAgent(BaseAgent):
    """Consumes availability events and performs booking attempts."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        message_bus: MessageBus,
        session_record: SessionRecord,
        provider: BookingProvider,
        lock_manager: LockManager | None = None,
        planner: AgentPlanner | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        super().__init__(config, message_bus=message_bus)
        self._record = session_record
        self._provider = provider
        self._locks = lock_manager
        self._planner = planner
        self._audit = audit_logger

    async def run(self) -> None:
        async for envelope in self.message_bus.subscribe(
            EventType.APPOINTMENT_AVAILABLE, session_id=self.config.session_id
        ):
            payload = envelope.payload or {}
            if payload.get("__bus_closed__"):
                break

            if self.should_stop():
                break

            slot = AppointmentAvailability.model_validate(envelope.payload)
            booking_request = AppointmentBookingRequest(
                session_id=self.config.session_id,
                slot=slot,
                user_profile=self._record.profile,
                preferences=self._record.preferences,
            )

            self.logger.info(
                "Received availability slot %s at %s; attempting booking",
                slot.slot_id,
                slot.slot_time,
            )
            if self._planner:
                self._planner.on_booking_attempt(self.config.session_id)
            try:
                # Ensure single booking per session via distributed lock if available
                if self._locks:
                    async with self._locks.lock(f"book:{self.config.session_id}") as acquired:
                        if not acquired:
                            self.logger.info("Another worker holds booking lock; skipping")
                            continue
                        result = await self._provider.book(booking_request, self._record)
                else:
                    result = await self._provider.book(booking_request, self._record)
            except Exception as exc:
                self.logger.exception("Booking provider error: %s", exc)
                result = AppointmentBookingResult(
                    session_id=self.config.session_id,
                    success=False,
                    slot=slot,
                    message=str(exc),
                )

            result_payload = result.model_dump(mode="json")
            envelope = EventEnvelope(
                type=EventType.BOOKING_RESULT,
                session_id=self.config.session_id,
                payload=result_payload,
            )
            await self.message_bus.publish(envelope)
            if result.success:
                self.logger.info("Successfully booked slot %s", slot.slot_id)
            else:
                self.logger.warning("Booking failed for slot %s: %s", slot.slot_id, result.message)
            if self._planner:
                self._planner.on_booking_result(self.config.session_id, result)
            if self._audit:
                try:
                    await self._audit.log(
                        event="booking_result",
                        session_id=self.config.session_id,
                        payload=result_payload,
                    )
                except Exception:
                    self.logger.debug("Failed to persist audit log", exc_info=True)
