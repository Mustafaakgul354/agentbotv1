"""Hybrid browser combining BQL stealth with Playwright flexibility."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any
import json

import httpx
from agentbot.utils.logging import get_logger

try:
    from playwright.async_api import Browser, Page, async_playwright
except Exception:
    Browser = Page = object  # type: ignore
    async_playwright = None  # type: ignore


logger = get_logger("HybridBrowser")


class HybridBrowserFactory:
    """Hybrid browser: uses BQL for stealth/CAPTCHA, then Playwright for operations."""

    def __init__(
        self,
        *,
        bql_endpoint: str,
        token: str,
        proxy: Optional[str] = None,
        proxy_country: Optional[str] = None,
        humanlike: bool = True,
        block_consent_modals: bool = True,
    ):
        self.bql_endpoint = bql_endpoint.rstrip("/")
        self.token = token
        self.proxy = proxy
        self.proxy_country = proxy_country
        self.humanlike = humanlike
        self.block_consent_modals = block_consent_modals
        self._pw = None
        self._lock = asyncio.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> {browser, page}

    async def _ensure_pw(self):
        """Ensure Playwright is initialized."""
        assert async_playwright is not None, "Install playwright for hybrid mode"
        async with self._lock:
            if self._pw is None:
                self._pw = await async_playwright().start()
            return self._pw

    def _get_bql_params(self) -> Dict[str, Any]:
        """Build BQL query parameters for stealth."""
        params: Dict[str, Any] = {
            "token": self.token,
        }
        if self.proxy:
            params["proxy"] = self.proxy
            params["proxySticky"] = "true"
            if self.proxy_country:
                params["proxyCountry"] = self.proxy_country
        if self.humanlike:
            params["humanlike"] = "true"
        if self.block_consent_modals:
            params["blockConsentModals"] = "true"
        return params

    async def _init_bql_session(self, url: str) -> str:
        """
        Initialize BQL session with stealth: navigate, handle CAPTCHA, return browserWSEndpoint.
        
        Returns:
            browserWSEndpoint for Playwright to connect via CDP
        """
        params = self._get_bql_params()
        
        # Step 1: Navigate and handle CAPTCHA via BQL mutation
        operation_name = "InitSession"
        mutation = f"""
mutation {operation_name} {{
  goto(url: "{url}") {{
    status
  }}
  verify(type: "cloudflare") {{
    found
    solved
    time
  }}
}}
"""
        
        headers = {"Content-Type": "application/json"}
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Execute BQL mutation to navigate and handle CAPTCHA
            logger.info("Initializing BQL session at %s with stealth", url)
            try:
                response = await client.post(
                    self.bql_endpoint,
                    params=params,
                    headers=headers,
                    json={"query": mutation, "operationName": operation_name},
                )
                response.raise_for_status()
                bql_result = response.json()
                
                if "errors" in bql_result:
                    logger.warning("BQL mutation errors: %s", bql_result.get("errors"))
                else:
                    verify_result = bql_result.get("data", {}).get("verify", {})
                    if verify_result.get("found"):
                        logger.info(
                            "Cloudflare challenge detected: solved=%s",
                            verify_result.get("solved"),
                        )
            except Exception as exc:
                logger.warning("BQL initialization error (continuing): %s", exc)
            
            # Step 2: Get browserWSEndpoint from Browserless.io
            # Browserless.io endpoints:
            # - /chrome (REST, returns JSON with wsEndpoint)
            # - /chrome/json/version (returns wsEndpoint)
            chrome_base = self.bql_endpoint.replace("/chrome/bql", "/chrome")
            
            logger.info("Fetching browserWSEndpoint from %s", chrome_base)
            
            try:
                # Try /chrome/json/version first (standard CDP endpoint)
                response = await client.get(
                    f"{chrome_base}/json/version",
                    params={"token": self.token},
                )
                response.raise_for_status()
                ws_data = response.json()
                ws_endpoint = ws_data.get("webSocketDebuggerUrl")
                
                if ws_endpoint:
                    logger.info("Got browserWSEndpoint from /chrome/json/version")
                    return ws_endpoint
            except Exception as exc:
                logger.warning("Failed to get endpoint from /chrome/json/version: %s", exc)
            
            try:
                # Fallback: try /chrome endpoint
                response = await client.get(
                    f"{chrome_base}",
                    params={"token": self.token},
                )
                response.raise_for_status()
                ws_data = response.json()
                ws_endpoint = ws_data.get("webSocketDebuggerUrl") or ws_data.get("wsEndpoint")
                
                if ws_endpoint:
                    logger.info("Got browserWSEndpoint from /chrome")
                    return ws_endpoint
            except Exception as exc:
                logger.warning("Failed to get endpoint from /chrome: %s", exc)
            
            # Fallback: construct WebSocket endpoint manually
            # Browserless.io format: ws://host/chrome/ws?token=...
            chrome_ws = chrome_base.replace("https://", "wss://").replace("http://", "ws://")
            ws_endpoint = f"{chrome_ws}/ws?token={self.token}"
            logger.info("Using constructed WebSocket endpoint: %s", ws_endpoint)
            return ws_endpoint

    @asynccontextmanager
    async def page(self, session_id: str) -> AsyncIterator[Page]:
        """Get or create a hybrid browser page (BQL session + Playwright)."""
        # Check if session already exists
        if session_id in self._sessions:
            page = self._sessions[session_id]["page"]
            try:
                yield page
            finally:
                pass
            return
        
        # Initialize new hybrid session
        async with self._lock:
            # Double-check after lock
            if session_id in self._sessions:
                page = self._sessions[session_id]["page"]
                try:
                    yield page
                finally:
                    pass
                return
            
            try:
                # Step 1: Initialize BQL session with stealth
                logger.info("Creating hybrid session %s", session_id)
                ws_endpoint = await self._init_bql_session("about:blank")
                
                # Step 2: Connect Playwright to BQL's browser via CDP
                pw = await self._ensure_pw()
                logger.info("Connecting Playwright to BQL browser via CDP: %s", ws_endpoint)
                
                browser = await pw.chromium.connect_over_cdp(ws_endpoint)
                
                # Get or create context and page
                contexts = browser.contexts
                if contexts:
                    context = contexts[0]
                else:
                    context = await browser.new_context(
                        locale="en-US",
                        timezone_id="Europe/Istanbul",
                    )
                
                pages = context.pages
                if pages:
                    page = pages[0]
                else:
                    page = await context.new_page()
                
                # Store session
                self._sessions[session_id] = {
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "ws_endpoint": ws_endpoint,
                }
                
                logger.info("Hybrid session %s initialized successfully", session_id)
                
                try:
                    yield page
                finally:
                    # Keep session alive for reuse
                    pass
                    
            except Exception as exc:
                logger.exception("Failed to create hybrid session %s: %s", session_id, exc)
                # Clean up on failure
                if session_id in self._sessions:
                    await self.close_session(session_id)
                raise

    async def close_session(self, session_id: str) -> None:
        """Close a specific session."""
        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions.pop(session_id)
                try:
                    browser = session.get("browser")
                    if browser:
                        await browser.close()
                    logger.info("Closed hybrid session %s", session_id)
                except Exception as exc:
                    logger.warning("Error closing session %s: %s", session_id, exc)

    async def close_all(self) -> None:
        """Close all sessions and Playwright instance."""
        async with self._lock:
            for session_id in list(self._sessions.keys()):
                session = self._sessions.pop(session_id)
                try:
                    browser = session.get("browser")
                    if browser:
                        await browser.close()
                except Exception as exc:
                    logger.warning("Error closing session %s: %s", session_id, exc)
            
            if self._pw:
                try:
                    await self._pw.stop()
                    self._pw = None
                except Exception as exc:
                    logger.warning("Error stopping Playwright: %s", exc)
            
            logger.info("Closed all hybrid sessions")
