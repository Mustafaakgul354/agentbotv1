"""BrowserQL client using browserless.io GraphQL API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional, Any
import json

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from agentbot.utils.logging import get_logger


logger = get_logger("BrowserQL")


class BrowserQLResponse:
    """Response object for BrowserQL network requests."""

    def __init__(self, url: str, status: int, response_body: str):
        self.url = url
        self.status = status
        self._response_body = response_body
        self._json_cache: Optional[Dict[str, Any]] = None

    async def json(self) -> Dict[str, Any]:
        """Parse response body as JSON."""
        if self._json_cache is None:
            try:
                self._json_cache = json.loads(self._response_body)
            except Exception:
                self._json_cache = {}
        return self._json_cache


class BrowserQLPage:
    """Wrapper for BrowserQL that mimics Playwright Page interface."""

    def __init__(self, session_id: str, browserql_client: BrowserQLClient):
        self.session_id = session_id
        self.client = browserql_client
        self.url = ""
        self._operation_counter = 0

    def _get_operation_name(self) -> str:
        """Generate unique operation name."""
        self._operation_counter += 1
        return f"Operation_{self._operation_counter}"

    async def goto(self, url: str, *, timeout: Optional[float] = None, wait_until: str = "load") -> None:
        """Navigate to URL."""
        self.url = url
        operation_name = self._get_operation_name()
        query = f"""
mutation {operation_name} {{
  goto(url: "{url}") {{
    status
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        goto_result = result.get("data", {}).get("goto", {})
        if goto_result.get("status") not in [200, 201, 204]:
            raise Exception(f"Navigation failed to {url} with status {goto_result.get('status')}")

    async def fill(self, selector: str, value: str) -> None:
        """Fill input field."""
        operation_name = self._get_operation_name()
        # Escape quotes in value
        escaped_value = value.replace('"', '\\"')
        query = f"""
mutation {operation_name} {{
  type(selector: "{selector}", text: "{escaped_value}") {{
    time
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        if "errors" in result:
            raise Exception(f"Fill failed for selector {selector}: {result.get('errors')}")

    async def click(self, selector: str, *, timeout: Optional[float] = None) -> None:
        """Click element."""
        operation_name = self._get_operation_name()
        query = f"""
mutation {operation_name} {{
  click(selector: "{selector}") {{
    time
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        if "errors" in result:
            raise Exception(f"Click failed for selector {selector}: {result.get('errors')}")

    async def wait_for_selector(
        self, selector: str, *, timeout: Optional[float] = None, state: str = "visible"
    ) -> None:
        """Wait for selector to appear."""
        operation_name = self._get_operation_name()
        timeout_ms = int(timeout * 1000) if timeout else 30000
        query = f"""
mutation {operation_name} {{
  waitForSelector(selector: "{selector}", timeout: {timeout_ms}) {{
    success
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        wait_result = result.get("data", {}).get("waitForSelector", {})
        if not wait_result.get("success"):
            raise Exception(f"Selector {selector} not found within timeout")

    async def wait_for_url(self, url_pattern: str, *, timeout: Optional[float] = None) -> None:
        """Wait for URL to match pattern."""
        # BrowserQL doesn't have direct wait_for_url, so we poll
        timeout_ms = int(timeout * 1000) if timeout else 30000
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) * 1000 < timeout_ms:
            operation_name = self._get_operation_name()
            query = f"""
query {operation_name} {{
  url
}}
"""
            result = await self.client.execute(query, operation_name)
            current_url = result.get("data", {}).get("url", "")
            if url_pattern.replace("**", "") in current_url:
                return
            await asyncio.sleep(0.5)
        raise Exception(f"URL pattern {url_pattern} not matched within timeout")

    async def wait_for_response(
        self, predicate: Any, *, timeout: Optional[float] = None
    ) -> Optional[BrowserQLResponse]:
        """Wait for network response matching predicate."""
        # BrowserQL doesn't have direct wait_for_response, so we'll use a polling approach
        timeout_ms = int(timeout * 1000) if timeout else 5000
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) * 1000 < timeout_ms:
            operation_name = self._get_operation_name()
            query = f"""
query {operation_name} {{
  networkLogs {{
    url
    status
    method
    responseBody
  }}
}}
"""
            result = await self.client.execute(query, operation_name)
            logs = result.get("data", {}).get("networkLogs", [])
            for log in logs:
                url = log.get("url", "")
                status = log.get("status", 0)
                # Simple predicate check - check if predicate matches
                try:
                    # Create a mock response object to check predicate
                    mock_response = BrowserQLResponse(url=url, status=status, response_body=log.get("responseBody", "{}"))
                    if predicate(mock_response):
                        return mock_response
                except Exception:
                    # If predicate check fails, try simple URL/status check
                    if ("calendar" in url or "slot" in url) and status == 200:
                        return BrowserQLResponse(url=url, status=status, response_body=log.get("responseBody", "{}"))
            await asyncio.sleep(0.5)
        return None

    async def query_selector_all(self, selector: str) -> list:
        """Query all matching elements."""
        operation_name = self._get_operation_name()
        query = f"""
query {operation_name} {{
  querySelectorAll(selector: "{selector}") {{
    success
    count
    elements {{
      selector
      text
    }}
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        data = result.get("data", {}).get("querySelectorAll", {})
        if data.get("success"):
            # Return mock elements that can be clicked
            elements = data.get("elements", [])
            return [BrowserQLElement(elem.get("selector"), self) for elem in elements]
        return []

    async def get_by_text(self, text: str, *, exact: bool = False) -> BrowserQLElement:
        """Get element by text."""
        operation_name = self._get_operation_name()
        exact_str = "true" if exact else "false"
        escaped_text = text.replace('"', '\\"')
        query = f"""
query {operation_name} {{
  getByText(text: "{escaped_text}", exact: {exact_str}) {{
    success
    selector
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        data = result.get("data", {}).get("getByText", {})
        if data.get("success"):
            return BrowserQLElement(data.get("selector"), self)
        raise Exception(f"Element with text '{text}' not found")

    async def inner_text(self, selector: str = "body") -> str:
        """Get inner text of element."""
        operation_name = self._get_operation_name()
        query = f"""
query {operation_name} {{
  getInnerText(selector: "{selector}") {{
    success
    text
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        data = result.get("data", {}).get("getInnerText", {})
        if data.get("success"):
            return data.get("text", "")
        return ""

    async def set_input_files(self, selector: str, file_path: str) -> None:
        """Set file input."""
        operation_name = self._get_operation_name()
        query = f"""
mutation {operation_name} {{
  setInputFiles(selector: "{selector}", files: ["{file_path}"]) {{
    success
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        if "errors" in result:
            raise Exception(f"Set input files failed for selector {selector}: {result.get('errors')}")

    async def verify(self, verify_type: str = "cloudflare", *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Verify Cloudflare challenge.
        
        Args:
            verify_type: Type of verification (default: "cloudflare")
            timeout: Timeout in seconds (default: 30000ms)
            
        Returns:
            Dict with found, solved, and time fields
            
        Note:
            This mutation does not incur unit costs, whereas the solve mutation does.
            Requires residential proxying to be enabled for Cloudflare verification.
        """
        operation_name = self._get_operation_name()
        timeout_ms = int(timeout * 1000) if timeout else 30000
        # Escape quotes in verify_type for GraphQL
        escaped_type = verify_type.replace('"', '\\"')
        query = f"""
mutation {operation_name} {{
  verify(type: "{escaped_type}", timeout: {timeout_ms}) {{
    found
    solved
    time
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        if "errors" in result:
            raise Exception(f"Verify failed: {result.get('errors')}")
        return result.get("data", {}).get("verify", {})

    async def wait_for_navigation(self, *, wait_until: str = "networkIdle", timeout: Optional[float] = None) -> Dict[str, Any]:
        """Wait for navigation to complete.
        
        Args:
            wait_until: When to consider navigation succeeded (default: "networkIdle")
            timeout: Timeout in seconds (default: 30000ms)
            
        Returns:
            Dict with status and time fields
        """
        operation_name = self._get_operation_name()
        timeout_ms = int(timeout * 1000) if timeout else 30000
        # Escape quotes in wait_until for GraphQL
        escaped_wait_until = wait_until.replace('"', '\\"')
        query = f"""
mutation {operation_name} {{
  waitForNavigation(waitUntil: "{escaped_wait_until}", timeout: {timeout_ms}) {{
    status
    time
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        if "errors" in result:
            raise Exception(f"Wait for navigation failed: {result.get('errors')}")
        return result.get("data", {}).get("waitForNavigation", {})

    async def query_selector(self, selector: str) -> Optional[BrowserQLElement]:
        """Query for a single matching element (returns None if not found)."""
        operation_name = self._get_operation_name()
        query = f"""
query {operation_name} {{
  querySelector(selector: "{selector}") {{
    success
    selector
  }}
}}
"""
        result = await self.client.execute(query, operation_name)
        data = result.get("data", {}).get("querySelector", {})
        if data.get("success"):
            return BrowserQLElement(data.get("selector"), self)
        return None

    async def verify_cloudflare_if_present(
        self,
        *,
        turnstile_selector: str = ".cf-turnstile",
        challenge_selector: str = 'a[href*="cloudflare.com"]',
        timeout: Optional[float] = None,
        wait_for_navigation: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Conditionally verify Cloudflare challenge if present.
        
        This method implements the conditional Cloudflare verification pattern:
        1. First checks for Cloudflare Turnstile widget (.cf-turnstile)
        2. If not found, checks for Cloudflare challenge page (a[href*="cloudflare.com"])
        3. If found, performs verification
        4. Optionally waits for navigation after verification
        
        Args:
            turnstile_selector: Selector for Cloudflare Turnstile widget (default: ".cf-turnstile")
            challenge_selector: Selector for Cloudflare challenge page (default: 'a[href*="cloudflare.com"]')
            timeout: Timeout in seconds for verification (default: 30000ms)
            wait_for_navigation: Whether to wait for navigation after verification (default: False)
            
        Returns:
            Dict with found, solved, and time fields if verification was performed, None otherwise
            
        Note:
            Requires residential proxying to be enabled for Cloudflare verification to work.
            This mutation does not incur unit costs.
        """
        # First, try to detect Cloudflare Turnstile
        try:
            await self.wait_for_selector(turnstile_selector, timeout=1.0)
            # Turnstile found, verify it
            verify_result = await self.verify(verify_type="cloudflare", timeout=timeout)
            return verify_result
        except Exception:
            # Turnstile not found, try challenge page
            pass
        
        # Check for Cloudflare challenge page
        try:
            await self.wait_for_selector(challenge_selector, timeout=1.0)
            # Challenge page found, verify it
            verify_result = await self.verify(verify_type="cloudflare", timeout=timeout)
            
            # If challenge page was detected, wait for navigation after verification
            if wait_for_navigation:
                await self.wait_for_navigation(wait_until="networkIdle", timeout=20.0)
            
            return verify_result
        except Exception:
            # No Cloudflare challenge detected
            return None


class BrowserQLElement:
    """Wrapper for BrowserQL element."""

    def __init__(self, selector: str, page: BrowserQLPage):
        self.selector = selector
        self.page = page

    async def click(self) -> None:
        """Click this element."""
        await self.page.click(self.selector)


class BrowserQLClient:
    """Client for BrowserQL GraphQL API."""

    def __init__(
        self,
        endpoint: str,
        token: Optional[str] = None,
        proxy: Optional[str] = None,
        proxy_country: Optional[str] = None,
        humanlike: bool = True,
        block_consent_modals: bool = True,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.proxy = proxy
        self.proxy_country = proxy_country
        self.humanlike = humanlike
        self.block_consent_modals = block_consent_modals
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self.endpoint,
                    timeout=60.0,
                )
            return self._client

    def _build_query_params(self) -> Dict[str, Any]:
        """Build query string parameters for BrowserQL API."""
        params: Dict[str, Any] = {}
        if self.token:
            params["token"] = self.token
        if self.proxy:
            params["proxy"] = self.proxy
            if self.proxy_country:
                params["proxyCountry"] = self.proxy_country
            params["proxySticky"] = "true"
        if self.humanlike:
            params["humanlike"] = "true"
        if self.block_consent_modals:
            params["blockConsentModals"] = "true"
        return params

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter())
    async def execute(self, query: str, operation_name: str) -> Dict[str, Any]:
        """Execute GraphQL query/mutation."""
        client = await self._ensure_client()
        params = self._build_query_params()
        headers = {"Content-Type": "application/json"}
        payload = {
            "query": query,
            "operationName": operation_name,
        }
        response = await client.post("", params=params, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class BrowserQLFactory:
    """Factory for creating BrowserQL pages per session."""

    def __init__(
        self,
        *,
        endpoint: str,
        token: Optional[str] = None,
        proxy: Optional[str] = None,
        proxy_country: Optional[str] = None,
        humanlike: bool = True,
        block_consent_modals: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.proxy = proxy
        self.proxy_country = proxy_country
        self.humanlike = humanlike
        self.block_consent_modals = block_consent_modals
        self._client = BrowserQLClient(
            endpoint=endpoint,
            token=token,
            proxy=proxy,
            proxy_country=proxy_country,
            humanlike=humanlike,
            block_consent_modals=block_consent_modals,
        )
        self._pages: Dict[str, BrowserQLPage] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def page(self, session_id: str) -> AsyncIterator[BrowserQLPage]:
        """Get or create a page for the session."""
        async with self._lock:
            if session_id not in self._pages:
                self._pages[session_id] = BrowserQLPage(session_id, self._client)
            page = self._pages[session_id]
        try:
            yield page
        finally:
            # Keep page alive for session reuse
            pass

    async def close(self) -> None:
        """Close all connections."""
        await self._client.close()
