"""HTTP client wrapper to share session state."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx


class HttpClient:
    """Shared HTTP client with cookie persistence per session."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def _ensure_client(self, session_id: str) -> httpx.AsyncClient:
        async with self._lock:
            if session_id not in self._clients:
                self._clients[session_id] = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
            return self._clients[session_id]

    @asynccontextmanager
    async def session(self, session_id: str) -> httpx.AsyncClient:
        client = await self._ensure_client(session_id)
        try:
            yield client
        finally:
            # Keep client open for reuse; teardown occurs in close_all()
            pass

    async def close_all(self) -> None:
        async with self._lock:
            for client in self._clients.values():
                await client.aclose()
            self._clients.clear()

