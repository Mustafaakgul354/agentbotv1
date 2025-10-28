"""Monitor agent implementation."""

from __future__ import annotations

import asyncio
from typing import Iterable, Protocol

from agentbot.agents.base import BaseAgent
from agentbot.core.message_bus import MessageBus
from agentbot.core.models import (
    AgentConfig,
    AppointmentAvailability,
    EventEnvelope,
    EventType,
)
from agentbot.data.session_store import SessionRecord


class AvailabilityProvider(Protocol):
    """Pluggable provider that encapsulates site-specific logic."""

    async def ensure_login(self, session: SessionRecord) -> None:
        ...

    async def check(self, session: SessionRecord) -> Iterable[AppointmentAvailability]:
        ...


class MonitorAgent(BaseAgent):
    """Polls the website for appointment availability."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        message_bus: MessageBus,
        session_record: SessionRecord,
        provider: AvailabilityProvider,
    ) -> None:
        super().__init__(config, message_bus=message_bus)
        self._record = session_record
        self._provider = provider

    async def setup(self) -> None:
        self.logger.info("Monitor agent ready for session %s", self.config.session_id)

    async def run(self) -> None:
        await self._provider.ensure_login(self._record)
        while not self.should_stop():
            try:
                slots = await self._provider.check(self._record)
                for slot in slots:
                    envelope = EventEnvelope(
                        type=EventType.APPOINTMENT_AVAILABLE,
                        session_id=self.config.session_id,
                        payload=slot.model_dump(mode="json"),
                    )
                    await self.message_bus.publish(envelope)
                    self.logger.info(
                        "Published availability slot %s at %s",
                        slot.slot_id,
                        slot.slot_time,
                    )
            except Exception as exc:
                self.logger.exception("Failed to check availability: %s", exc)
            await asyncio.sleep(self.config.poll_interval_seconds)

