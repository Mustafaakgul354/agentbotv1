"""Playwright context utilities with stealth, proxy hooks, and persistent dirs."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional, Sequence, Callable

from agentbot.utils.logging import get_logger


logger = get_logger("Browser")


try:  # optional import to keep base install light
    from playwright.async_api import BrowserContext, Page, async_playwright
except Exception:  # pragma: no cover - only loaded when extra is installed
    BrowserContext = Page = object  # type: ignore
    async_playwright = None  # type: ignore

try:  # optional stealth add-on (mirrors playwright-extra stealth plugin)
    from playwright_stealth import stealth_async
except Exception:  # pragma: no cover - only loaded when extra is installed
    stealth_async = None  # type: ignore


class BrowserFactory:
    """Creates persistent Playwright contexts per session id (user data dir)."""

    DEFAULT_LAUNCH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ]

    def __init__(
        self,
        *,
        headless: bool = True,
        user_data_root: Path | None = None,
        proxy: Optional[str] = None,
        extra_launch_args: Sequence[str] | None = None,
        enable_stealth: bool = True,
    ) -> None:
        self.headless = headless
        self.user_data_root = user_data_root or Path(".user_data").resolve()
        self.proxy = proxy
        self.enable_stealth = enable_stealth
        self._lock = asyncio.Lock()
        self._pw = None
        self._launch_args = list(self.DEFAULT_LAUNCH_ARGS)
        self._stealth_warning_logged = False
        if extra_launch_args:
            for arg in extra_launch_args:
                if arg not in self._launch_args:
                    self._launch_args.append(arg)

    async def _ensure_pw(self):
        assert async_playwright is not None, "Install with [browser] extra to use Playwright"
        async with self._lock:
            if self._pw is None:
                self._pw = await async_playwright().start()
            return self._pw

    def _cleanup_chromium_locks(self, user_dir: Path) -> None:
        """Clean up Chromium lock files from previous crashed/stopped processes."""
        lock_files = [
            "SingletonLock",
            "SingletonCookie", 
            "SingletonSocket",
        ]
        
        for lock_name in lock_files:
            lock_path = user_dir / lock_name
            if lock_path.exists():
                try:
                    # If it's a symlink, also try to remove the target
                    if lock_path.is_symlink():
                        target = lock_path.readlink()
                        lock_path.unlink()
                        logger.debug(f"Removed stale lock symlink: {lock_path} -> {target}")
                        # Try to remove the target file if it exists in the same directory
                        target_path = user_dir / target if not target.is_absolute() else target
                        if target_path.exists() and target_path.is_file():
                            try:
                                target_path.unlink()
                                logger.debug(f"Removed stale lock target: {target_path}")
                            except Exception:
                                pass  # Target might be in /tmp or elsewhere
                    else:
                        lock_path.unlink()
                        logger.debug(f"Removed stale lock file: {lock_path}")
                except Exception as e:
                    logger.warning(f"Could not remove lock file {lock_path}: {e}")

    async def _enable_context_stealth(
        self, context: BrowserContext
    ) -> Optional[Callable[[Page], None]]:
        """Enable stealth scripts (playwright-stealth) on every page if available."""
        if not self.enable_stealth or stealth_async is None:
            return None

        async def _stealth_page(page: Page) -> None:
            try:
                await stealth_async(page)
                logger.debug("Stealth scripts applied to page %s", page.url)
            except Exception as exc:  # pragma: no cover - best effort hook
                logger.warning("Failed to apply stealth scripts: %s", exc)

        # Apply to any pre-existing pages (persistent contexts may have tabs)
        for page in context.pages:
            await _stealth_page(page)

        def _handler(page: Page) -> None:
            asyncio.create_task(_stealth_page(page))

        context.on("page", _handler)
        logger.info("playwright-stealth enabled for persistent context")
        return _handler

    @asynccontextmanager
    async def context(self, session_id: str) -> AsyncIterator[BrowserContext]:
        pw = await self._ensure_pw()
        user_dir = self.user_data_root / session_id
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # Clean up Chromium lock files if they exist (from previous crashed/stopped processes)
        self._cleanup_chromium_locks(user_dir)
        
        logger.info(
            "Launching Chromium context (headless=%s, dir=%s)", self.headless, user_dir
        )
        context = await pw.chromium.launch_persistent_context(
            str(user_dir),
            headless=self.headless,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=self._launch_args,
            proxy={"server": self.proxy} if self.proxy else None,
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            accept_downloads=True,
            has_touch=False,
            is_mobile=False,
        )
        stealth_handler = await self._enable_context_stealth(context)
        try:
            # minimal stealth: remove webdriver flag
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            yield context
        finally:
            if stealth_handler:
                try:
                    context.off("page", stealth_handler)
                except Exception:
                    pass
            await context.close()

    @asynccontextmanager
    async def page(self, session_id: str) -> AsyncIterator[Page]:
        async with self.context(session_id) as ctx:
            page = await ctx.new_page()
            yield page
