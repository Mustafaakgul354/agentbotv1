"""Monitor agent implementation."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Iterable, Optional, Protocol

from agentbot.agents.base import BaseAgent
from agentbot.core.message_bus import MessageBus
from agentbot.core.models import (
    AgentConfig,
    AppointmentAvailability,
    EventEnvelope,
    EventType,
)
from agentbot.core.planner import AgentPlanner
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
        planner: Optional[AgentPlanner] = None,
    ) -> None:
        super().__init__(config, message_bus=message_bus)
        self._record = session_record
        self._provider = provider
        self._planner = planner

    async def setup(self) -> None:
        self.logger.info("Monitor agent ready for session %s", self.config.session_id)
        if self._planner:
            self._planner.on_monitoring(self.config.session_id)

    async def run(self) -> None:
        await self._provider.ensure_login(self._record)
        while not self.should_stop():
            status = "ok"
            try:
                slots = await self._provider.check(self._record)
                for slot in slots:
                    envelope = EventEnvelope(
                        type=EventType.APPOINTMENT_AVAILABLE,
                        session_id=self.config.session_id,
                        payload=slot.model_dump(mode="json"),
                    )
                    await self.message_bus.publish(envelope)
                    if self._planner:
                        self._planner.on_availability(self.config.session_id, slot)
                    self.logger.info(
                        "Published availability slot %s at %s",
                        slot.slot_id,
                        slot.slot_time,
                    )
            except Exception as exc:
                status = "error"
                self.logger.exception("Failed to check availability: %s", exc)
            finally:
                await self._emit_heartbeat(status=status)
            if self.should_stop():
                break
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _emit_heartbeat(self, *, status: str) -> None:
        envelope = EventEnvelope(
            type=EventType.HEARTBEAT,
            session_id=self.config.session_id,
            payload={
                "agent": self._name,
                "status": status,
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        )
        try:
            await self.message_bus.publish(envelope)
        except Exception:
            self.logger.debug("Failed to emit heartbeat", exc_info=True)
