"""Common agent abstractions."""

from __future__ import annotations

import abc
import asyncio
from typing import Optional

# Change this import to avoid circular dependency
from agentbot.core.message_bus import MessageBus
from agentbot.core.models import AgentConfig
from agentbot.utils.logging import get_logger


class BaseAgent(abc.ABC):
    """Abstract agent with lifecycle helpers."""

    def __init__(self, config: AgentConfig, *, message_bus: MessageBus, name: Optional[str] = None) -> None:
        self.config = config
        self.message_bus = message_bus
        self._name = name or self.__class__.__name__
        self.logger = get_logger(self._name)
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.logger.info("Starting agent for session %s", self.config.session_id)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_wrapper(), name=f"{self._name}-{self.config.session_id}")

    async def stop(self) -> None:
        self.logger.info("Stopping agent for session %s", self.config.session_id)
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_wrapper(self) -> None:
        try:
            await self.setup()
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - ensure errors are logged
            self.logger.exception("Unhandled exception: %s", exc)
        finally:
            await self.teardown()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    async def setup(self) -> None:
        """Optional hook executed once before run loop."""

    async def teardown(self) -> None:
        """Optional hook executed once after run loop."""

    @abc.abstractmethod
    async def run(self) -> None:
        """Main agent body."""

