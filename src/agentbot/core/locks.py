"""Abstract interfaces for distributed locks."""

from __future__ import annotations

import abc
from typing import Protocol


class AsyncLock(Protocol):
    async def __aenter__(self) -> bool: ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...


class LockManager(abc.ABC):
    @abc.abstractmethod
    def lock(self, key: str, ttl_ms: int = 30000) -> AsyncLock:  # pragma: no cover - interface
        """Return an async context manager that attempts to acquire a lock."""
        raise NotImplementedError


