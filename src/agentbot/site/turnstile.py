"""Helpers to detect Cloudflare Turnstile and wait for challenge resolution."""

from __future__ import annotations

from typing import Optional


async def await_turnstile_if_present(page, *, timeout: int = 15000) -> None:
    """Wait briefly if a Turnstile widget is present.

    This does not solve challenges; it simply gives time for managed/automatic
    solutions to complete (e.g., Private Access Token or human).
    """
    try:
        # If widget exists, wait up to timeout for it to disappear or succeed
        widget = await page.query_selector("iframe[src*='turnstile']")
        if widget:
            await page.wait_for_timeout(min(timeout, 15000))
    except Exception:
        pass


