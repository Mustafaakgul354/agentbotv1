"""Playwright context utilities with stealth, proxy hooks, and persistent dirs."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from agentbot.utils.logging import get_logger


logger = get_logger("Browser")


try:  # optional import to keep base install light
    from playwright.async_api import BrowserContext, Page, async_playwright
except Exception:  # pragma: no cover - only loaded when extra is installed
    BrowserContext = Page = object  # type: ignore
    async_playwright = None  # type: ignore


class BrowserFactory:
    """Creates persistent Playwright contexts per session id (user data dir)."""

    def __init__(self, *, headless: bool = False, user_data_root: Path | None = None, proxy: Optional[str] = None) -> None:
        self.headless = headless
        self.user_data_root = user_data_root or Path(".user_data").resolve()
        self.proxy = proxy
        self._lock = asyncio.Lock()
        self._playwright_instance = None

    async def _ensure_playwright_instance(self):
        assert async_playwright is not None, "Install with [browser] extra to use Playwright"
        async with self._lock:
            if self._playwright_instance is None:
                self._playwright_instance = await async_playwright().start()
            return self._playwright_instance

    @asynccontextmanager
    async def context(self, session_id: str) -> AsyncIterator[BrowserContext]:
        playwright_instance = await self._ensure_playwright_instance()
        user_dir = self.user_data_root / session_id
        user_dir.mkdir(parents=True, exist_ok=True)
        browser_context = await playwright_instance.chromium.launch_persistent_context(
            str(user_dir),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            proxy={"server": self.proxy} if self.proxy else None,
            locale="en-US",
            timezone_id="Europe/Istanbul",
        )
        try:
            # minimal stealth: remove webdriver flag
            await browser_context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            yield browser_context
        finally:
            await browser_context.close()

    @asynccontextmanager
    async def page(self, session_id: str) -> AsyncIterator[Page]:
        async with self.context(session_id) as browser_context:
            page = await browser_context.new_page()
            yield page


