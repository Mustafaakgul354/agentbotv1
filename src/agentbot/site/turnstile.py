"""Helpers to detect Cloudflare Turnstile and wait for challenge resolution."""

from __future__ import annotations

from typing import Optional, Any
import asyncio


async def await_turnstile_if_present(page: Any, *, timeout: int = 15000) -> None:
    """Wait briefly if a Turnstile widget is present, or verify Cloudflare challenge if using BrowserQL/BQL stealth.

    For Playwright pages: This does not solve challenges; it simply gives time for managed/automatic
    solutions to complete (e.g., Private Access Token or human).
    
    For BrowserQL pages: Uses the verify mutation to solve Cloudflare challenges automatically.
    Requires residential proxying to be enabled for Cloudflare verification to work.
    
    For Hybrid mode (BQL + Playwright): BQL stealth is active during initialization, but we still
    check for challenge indicators and wait appropriately.
    
    Eğer Cloudflare challenge tetiklenirse, BQL stealth ile aşın.
    If Cloudflare challenge is triggered, bypass it with BQL stealth.
    """
    # Check if page is BrowserQLPage (has verify method)
    if hasattr(page, 'verify_cloudflare_if_present'):
        # BrowserQL: Use verify mutation to solve Cloudflare challenges automatically
        try:
            timeout_sec = timeout / 1000.0 if timeout else None
            result = await page.verify_cloudflare_if_present(
                timeout=timeout_sec,
                wait_for_navigation=True  # Wait for navigation after verification
            )
            if result:
                # Verification was performed and succeeded
                return
        except Exception:
            # If verification fails, fall through to Playwright-style wait
            pass
    
    # Check for Cloudflare challenge indicators (works for both Playwright and Hybrid mode)
    challenge_indicators = [
        "iframe[src*='turnstile']",
        'a[href*="cloudflare.com"]',
        'div:has-text("Checking your browser")',
        'div:has-text("Just a moment")',
        'div:has-text("DDoS protection by Cloudflare")',
        '.cf-browser-verification',
        '#challenge-form',
        '.cf-challenge-form',
        '[data-ray]',  # Cloudflare challenge attribute
    ]
    
    challenge_detected = False
    for indicator in challenge_indicators:
        try:
            element = await page.query_selector(indicator)
            if element:
                challenge_detected = True
                break
        except Exception:
            continue
    
    # Also check page content for Cloudflare indicators
    if not challenge_detected:
        try:
            content = await page.content()
            if any(indicator in content.lower() for indicator in [
                "cloudflare",
                "checking your browser",
                "just a moment",
                "ddos protection"
            ]):
                challenge_detected = True
        except Exception:
            pass
    
    # If challenge detected, wait for it to resolve
    if challenge_detected:
        try:
            # Wait for turnstile widget to resolve or disappear
            widget = await page.query_selector("iframe[src*='turnstile']")
            if widget:
                # Wait for widget to disappear or become invisible
                wait_time = min(timeout, 15000)
                if hasattr(page, 'wait_for_timeout'):
                    await page.wait_for_timeout(wait_time)
                else:
                    await asyncio.sleep(wait_time / 1000.0)
            
            # For Hybrid mode: BQL stealth should handle challenges during initialization,
            # but we wait a bit more to ensure navigation completes
            if hasattr(page, 'wait_for_timeout'):
                await page.wait_for_timeout(2000)
            else:
                await asyncio.sleep(2.0)
        except Exception:
            pass
    else:
        # No challenge detected, but still wait briefly for any async turnstile widgets
        try:
            widget = await page.query_selector("iframe[src*='turnstile']")
            if widget:
                wait_time = min(timeout, 5000)
                if hasattr(page, 'wait_for_timeout'):
                    await page.wait_for_timeout(wait_time)
                else:
                    await asyncio.sleep(wait_time / 1000.0)
        except Exception:
            pass


