"""Runtime orchestration for agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional

# Import BaseAgent only for type checking to avoid circular import
if TYPE_CHECKING:
    from agentbot.agents.base import BaseAgent

from agentbot.core.message_bus import MessageBus
from agentbot.core.models import AgentConfig
from agentbot.core.planner import AgentPlanner
from agentbot.data.session_store import SessionRecord, SessionStore
from agentbot.services.audit_logger import AuditLogger
from agentbot.utils.logging import get_logger


AgentFactory = Callable[[AgentConfig, SessionRecord], "BaseAgent"]


@dataclass(slots=True)
class AgentBundle:
    session_id: str
    monitor_agent: "BaseAgent"
    booking_agent: "BaseAgent"


class AgentRuntime:
    """High-level runtime that spins up monitor/booking agents for each user session."""

    def __init__(
        self,
        *,
        session_store: SessionStore,
        message_bus: Optional[MessageBus] = None,
        planner: Optional[AgentPlanner] = None,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self.session_store = session_store
        self.message_bus = message_bus or MessageBus()
        self.logger = get_logger("AgentRuntime")
        self.planner = planner or AgentPlanner()
        self.audit_logger = audit_logger
        self._bundles: List[AgentBundle] = []
        self._started = False
        self._lock = asyncio.Lock()

    async def bootstrap(
        self,
        monitor_factory: AgentFactory,
        booking_factory: AgentFactory,
    ) -> None:
        """Instantiate agents for every persisted session."""
        self.logger.info("Bootstrapping agents from session store")
        sessions = await self.session_store.list_sessions()
        for record in sessions:
            config = record.to_agent_config()
            monitor_agent = monitor_factory(config, record)
            booking_agent = booking_factory(config, record)
            self._bundles.append(
                AgentBundle(
                    session_id=record.session_id,
                    monitor_agent=monitor_agent,
                    booking_agent=booking_agent,
                )
            )

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            self.logger.info("Starting %d agent bundles", len(self._bundles))
            for bundle in self._bundles:
                await bundle.monitor_agent.start()
                await bundle.booking_agent.start()
            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            self.logger.info("Stopping agents")
            await asyncio.gather(
                *(bundle.monitor_agent.stop() for bundle in self._bundles),
                *(bundle.booking_agent.stop() for bundle in self._bundles),
                return_exceptions=True,
            )
            self._bundles.clear()
            self._started = False

    async def run_forever(self) -> None:
        """Convenience helper for long-running processes."""
        await self.start()
        self.logger.info("Runtime is now running. Press Ctrl+C to exit.")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")
        finally:
            await self.stop()
            await self.message_bus.close()
