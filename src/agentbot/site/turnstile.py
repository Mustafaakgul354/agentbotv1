"""Helpers to detect Cloudflare Turnstile and wait for challenge resolution."""

from __future__ import annotations

from typing import Optional, Any


async def await_turnstile_if_present(page: Any, *, timeout: int = 15000) -> None:
    """Wait briefly if a Turnstile widget is present, or verify Cloudflare challenge if using BrowserQL.

    For Playwright pages: This does not solve challenges; it simply gives time for managed/automatic
    solutions to complete (e.g., Private Access Token or human).
    
    For BrowserQL pages: Uses the verify mutation to solve Cloudflare challenges automatically.
    Requires residential proxying to be enabled for Cloudflare verification to work.
    """
    # Check if page is BrowserQLPage (has verify method)
    if hasattr(page, 'verify_cloudflare_if_present'):
        # BrowserQL: Use verify mutation to solve Cloudflare challenges
        try:
            timeout_sec = timeout / 1000.0 if timeout else None
            result = await page.verify_cloudflare_if_present(
                timeout=timeout_sec,
                wait_for_navigation=False
            )
            if result:
                # Verification was performed and succeeded
                return
        except Exception:
            # If verification fails, fall through to Playwright-style wait
            pass
    
    # Playwright: Wait for turnstile widget to resolve
    try:
        # If widget exists, wait up to timeout for it to disappear or succeed
        widget = await page.query_selector("iframe[src*='turnstile']")
        if widget:
            # Playwright has wait_for_timeout, BrowserQL doesn't
            if hasattr(page, 'wait_for_timeout'):
                await page.wait_for_timeout(min(timeout, 15000))
            else:
                # For BrowserQL, use asyncio.sleep
                import asyncio
                await asyncio.sleep(min(timeout, 15000) / 1000.0)
    except Exception:
        pass


