"""Hybrid browser combining BQL stealth with Playwright flexibility."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any

import httpx
from agentbot.utils.logging import get_logger

try:
    from playwright.async_api import Browser, Page, BrowserContext, CDPSession, async_playwright
except Exception:
    Browser = Page = BrowserContext = CDPSession = object  # type: ignore
    async_playwright = None  # type: ignore


logger = get_logger("HybridBrowser")


class HybridBrowserFactory:
    """Hybrid browser: uses BQL for stealth/CAPTCHA, then Playwright for operations.
    
    Features:
    - BQL stealth initialization with CAPTCHA solving
    - Playwright API for flexible automation
    - LiveURL support for monitoring and debugging
    - CDP session for advanced browser control
    - Screenshot capabilities
    """

    def __init__(
        self,
        *,
        bql_endpoint: str,
        token: str,
        proxy: Optional[str] = None,
        proxy_country: Optional[str] = None,
        humanlike: bool = True,
        block_consent_modals: bool = True,
        enable_live_url: bool = False,
        hybrid: bool = True,
    ):
        self.bql_endpoint = bql_endpoint.rstrip("/")
        self.token = token
        self.proxy = proxy
        self.proxy_country = proxy_country
        self.humanlike = humanlike
        self.block_consent_modals = block_consent_modals
        self.enable_live_url = enable_live_url
        self.hybrid = hybrid
        self._pw = None
        self._lock = asyncio.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> {browser, page, cdp_session, live_url}

    async def _ensure_pw(self):
        """Ensure Playwright is initialized."""
        assert async_playwright is not None, "Install playwright for hybrid mode"
        async with self._lock:
            if self._pw is None:
                self._pw = await async_playwright().start()
            return self._pw

    def _get_bql_params(self, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Build BQL query parameters for stealth."""
        params: Dict[str, Any] = {
            "token": self.token,
        }
        if timeout:
            params["timeout"] = timeout
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

    async def _init_bql_session(self, url: str, verify_cloudflare: bool = False) -> str:
        """
        Initialize BQL session with stealth: navigate, handle CAPTCHA, return browserWSEndpoint.
        
        Args:
            url: URL to navigate to
            verify_cloudflare: Whether to verify Cloudflare challenges (requires residential proxy)
        
        Returns:
            browserWSEndpoint for Playwright to connect via CDP
        """
        # 30 seconds timeout for session (BrowserQL basic plan limit)
        params = self._get_bql_params(timeout=30000)
        
        # Step 1: Navigate + optionally verify Cloudflare + ask BQL to hand us a CDP WebSocket endpoint
        operation_name = "ReconnectToPlaywright"
        
        # Build mutation with optional Cloudflare verification
        cloudflare_mutation = ""
        if verify_cloudflare:
            cloudflare_mutation = """
  verify(type: "cloudflare") {
    found
    solved
    time
  }"""
        
        mutation = f"""
mutation {operation_name}($url: String!) {{
  goto(url: $url, waitUntil: networkIdle, timeout: 20000) {{
    status
  }}{cloudflare_mutation}
  reconnect(timeout: 5000) {{
    browserWSEndpoint
  }}
}}
"""
        
        variables = {"url": url}
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "query": mutation,
            "operationName": operation_name,
            "variables": variables,
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Execute BQL mutation to navigate and fetch the websocket endpoint
            logger.info("Initializing BQL session for URL: %s", url)
            if verify_cloudflare:
                logger.info("Cloudflare verification enabled (requires residential proxy)")
            
            try:
                response = await client.post(
                    self.bql_endpoint,
                    params=params,
                    headers=headers,
                    json=payload,
                )
                
                if not response.is_success:
                    error_text = await response.aread()
                    raise Exception(f"Failed to initialize session:\n{error_text.decode()}")
                
                bql_result = response.json()
                
                if "errors" in bql_result:
                    logger.warning("BQL mutation errors: %s", bql_result.get("errors"))
                    raise Exception(f"BQL errors: {bql_result.get('errors')}")
                
                data = bql_result.get("data", {})
                
                # Log goto status
                goto_status = data.get("goto", {}).get("status")
                if goto_status:
                    logger.info("BQL goto status: %s", goto_status)
                
                # Log Cloudflare verification result if enabled
                if verify_cloudflare:
                    verify_result = data.get("verify", {})
                    if verify_result:
                        logger.info(
                            "Cloudflare verification: found=%s, solved=%s, time=%sms",
                            verify_result.get("found"),
                            verify_result.get("solved"),
                            verify_result.get("time"),
                        )
                
                # Get WebSocket endpoint
                reconnect = data.get("reconnect", {})
                ws_endpoint = reconnect.get("browserWSEndpoint")
                expires_in = reconnect.get("expiresIn")
                
                if ws_endpoint:
                    logger.info(
                        "Session initialized! browserWSEndpoint received (expires in %sms)",
                        expires_in
                    )
                    # Append token to WebSocket endpoint
                    endpoint_with_token = f"{ws_endpoint}?token={self.token}"
                    return endpoint_with_token
                
                logger.warning("reconnect did not return browserWSEndpoint: %s", reconnect)
                raise Exception("No browserWSEndpoint in reconnect response")
                
            except Exception as exc:
                logger.error("BQL initialization failed: %s", exc)
                raise

    async def _setup_cdp_session(self, context: BrowserContext, page: Page) -> Optional[CDPSession]:
        """Setup CDP session for advanced browser control and LiveURL support.
        
        Returns:
            CDPSession if successfully created, None otherwise
        """
        try:
            cdp_session = await context.new_cdp_session(page)
            
            # Get LiveURL if enabled
            if self.enable_live_url:
                try:
                    result = await cdp_session.send("Browserless.liveURL")
                    live_url = result.get("liveURL")
                    if live_url:
                        logger.info("Monitor or interact with your session at: %s", live_url)
                        return cdp_session
                except Exception as exc:
                    logger.warning("Failed to get LiveURL: %s", exc)
            
            return cdp_session
        except Exception as exc:
            logger.warning("Failed to create CDP session: %s", exc)
            return None

    async def wait_for_live_complete(self, session_id: str) -> None:
        """Wait for the LiveURL session to complete (user closes the LiveURL).
        
        This is useful when you want to:
        1. Share a LiveURL with an end-user
        2. Wait for them to finish interacting with the browser
        3. Continue automation after they're done
        
        Args:
            session_id: The session ID to wait for
            
        Raises:
            ValueError: If session doesn't exist or CDP session is not available
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        cdp_session = session.get("cdp_session")
        
        if not cdp_session:
            raise ValueError(f"CDP session not available for {session_id}")
        
        logger.info("Waiting for LiveURL session to complete...")
        
        # Wait for the Browserless.liveComplete event
        await asyncio.create_task(
            self._wait_for_cdp_event(cdp_session, "Browserless.liveComplete")
        )
        
        logger.info("LiveURL session completed")
    
    async def _wait_for_cdp_event(self, cdp_session: CDPSession, event_name: str) -> None:
        """Wait for a specific CDP event."""
        future = asyncio.Future()
        
        def handler(params):
            if not future.done():
                future.set_result(params)
        
        cdp_session.on(event_name, handler)
        try:
            await future
        finally:
            # Clean up handler
            try:
                cdp_session.remove_listener(event_name, handler)
            except Exception:
                pass

    @asynccontextmanager
    async def page(self, session_id: str, verify_cloudflare: bool = False) -> AsyncIterator[Page]:
        """Get or create a hybrid browser page (BQL session + Playwright).
        
        Args:
            session_id: Unique identifier for this session
            verify_cloudflare: Whether to verify Cloudflare challenges during initialization
            
        Yields:
            Playwright Page object connected to BQL browser
        """
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
                if not self.hybrid:
                    # BQL bypass: Launch a regular Playwright browser
                    logger.info("BQL bypassed. Launching regular Playwright session %s", session_id)
                    pw = await self._ensure_pw()
                    browser = await pw.chromium.launch()
                    context = await browser.new_context(
                        locale="en-US",
                        timezone_id="Europe/Istanbul",
                    )
                    page = await context.new_page()

                else:
                    # Step 1: Initialize BQL session with stealth
                    logger.info("Creating hybrid session %s", session_id)
                    ws_endpoint = await self._init_bql_session("about:blank", verify_cloudflare=verify_cloudflare)
                    
                    # Step 2: Connect Playwright to BQL's browser via CDP
                    pw = await self._ensure_pw()
                    logger.info("Connecting Playwright to BQL browser via CDP")
                    
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
                
                # Step 3: Setup CDP session for advanced control and LiveURL
                cdp_session = await self._setup_cdp_session(context, page)
                
                # Store session
                self._sessions[session_id] = {
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "cdp_session": cdp_session,
                }
                
                logger.info("Session %s initialized successfully (hybrid=%s)", session_id, self.hybrid)
                
                try:
                    yield page
                finally:
                    # Keep session alive for reuse
                    pass
                    
            except Exception as exc:
                logger.exception("Failed to create session %s: %s", session_id, exc)
                # Clean up on failure
                if session_id in self._sessions:
                    await self.close_session(session_id)
                raise

    def get_live_url(self, session_id: str) -> Optional[str]:
        """Get the LiveURL for a session if available.
        
        Args:
            session_id: The session ID
            
        Returns:
            LiveURL string if available, None otherwise
        """
        if session_id not in self._sessions:
            return None
        
        return self._sessions[session_id].get("live_url")
    
    async def screenshot(
        self,
        session_id: str,
        path: Optional[str] = None,
        full_page: bool = False
    ) -> bytes:
        """Capture a screenshot of the session.
        
        Args:
            session_id: The session ID
            path: Optional file path to save screenshot
            full_page: Whether to capture full scrollable page
            
        Returns:
            Screenshot as bytes
            
        Raises:
            ValueError: If session doesn't exist
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        page = self._sessions[session_id]["page"]
        screenshot_bytes = await page.screenshot(path=path, full_page=full_page)
        
        if path:
            logger.info("Screenshot saved to: %s", path)
        
        return screenshot_bytes

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
