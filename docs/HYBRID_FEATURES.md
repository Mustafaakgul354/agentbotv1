# BrowserQL Hybrid Mode - New Features

## Overview

This document describes the enhanced features added to the BrowserQL Hybrid Mode implementation based on the official Browserless.io Hybrid guide.

## What's New

### 1. LiveURL Support

**What it is:** A real-time monitoring URL that allows you to watch and interact with browser sessions as they run.

**Use cases:**
- Debug automation flows in real-time
- Allow end-users to manually complete steps (e.g., 2FA, CAPTCHA)
- Monitor session progress
- Manual intervention when automation gets stuck

**How to use:**

```python
factory = HybridBrowserFactory(
    bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
    token="your-token",
    enable_live_url=True,  # Enable LiveURL
)

async with factory.page("my-session") as page:
    # Get the LiveURL
    live_url = factory.get_live_url("my-session")
    print(f"Monitor at: {live_url}")
    
    # Share with user or open in browser
    # The URL can be embedded in an iframe or opened in a new tab
```

### 2. Wait for LiveURL Completion

**What it is:** Ability to pause automation and wait for a user to finish interacting via LiveURL.

**Use cases:**
- Hybrid automation: bot does initial setup, user completes sensitive steps
- Manual verification steps
- User-driven form filling
- Interactive debugging

**How to use:**

```python
async with factory.page("my-session") as page:
    # Do initial automation
    await page.goto("https://example.com/login")
    
    # Get LiveURL and share with user
    live_url = factory.get_live_url("my-session")
    send_email(user, f"Complete login at: {live_url}")
    
    # Wait for user to finish
    await factory.wait_for_live_complete("my-session")
    
    # Continue automation after user is done
    await page.goto("https://example.com/dashboard")
```

### 3. Enhanced Cloudflare Verification

**What it is:** Automatic Cloudflare challenge solving during session initialization.

**Benefits:**
- No unit costs (BQL's verify mutation is free)
- Solved before Playwright connects
- Works with Turnstile and challenge pages
- Requires residential proxy

**How to use:**

```python
# Enable Cloudflare verification during initialization
async with factory.page("my-session", verify_cloudflare=True) as page:
    # Cloudflare is already solved!
    await page.goto("https://cloudflare-protected-site.com")
```

### 4. CDP Session Management

**What it is:** Chrome DevTools Protocol session for advanced browser control.

**Benefits:**
- Access to low-level browser APIs
- Custom event listeners
- Advanced debugging
- LiveURL functionality

**Implementation:**
- Automatically created when session starts
- Stored in session data
- Used internally for LiveURL events
- Available for custom use cases

### 5. Screenshot Capture API

**What it is:** Convenient API for capturing screenshots at any point.

**Features:**
- Capture current viewport or full page
- Save to file or get as bytes
- Integrated with session management

**How to use:**

```python
# Capture viewport
await factory.screenshot("my-session", path="screenshot.png")

# Capture full scrollable page
await factory.screenshot(
    "my-session",
    path="full-page.png",
    full_page=True
)

# Get as bytes
screenshot_bytes = await factory.screenshot("my-session")
```

### 6. Improved BQL Mutation

**What it is:** Enhanced GraphQL mutation for session initialization.

**Improvements:**
- Uses `reconnect` mutation for WebSocket endpoint
- Supports optional Cloudflare verification
- Waits for `networkIdle` before connecting Playwright
- Includes session timeout configuration
- Better error handling and logging

**GraphQL mutation:**

```graphql
mutation ReconnectToPlaywright($url: String!) {
  goto(url: $url, waitUntil: networkIdle) {
    status
  }
  verify(type: "cloudflare") {  # Optional
    found
    solved
    time
  }
  reconnect(timeout: 30000) {
    browserWSEndpoint
    expiresIn
  }
}
```

## Configuration Changes

### New Parameters

#### `enable_live_url` (bool, default: False)
Enable LiveURL monitoring for sessions.

```python
factory = HybridBrowserFactory(
    # ... other params ...
    enable_live_url=True,
)
```

Or via environment variable:
```bash
export BROWSERQL_ENABLE_LIVE_URL=true
```

#### `verify_cloudflare` (bool, default: False)
Enable Cloudflare verification during session initialization.

```python
async with factory.page("session-id", verify_cloudflare=True) as page:
    # Cloudflare already solved
    pass
```

### Updated YAML Config

```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-browserless-token"
  proxy: "residential"           # Required for Cloudflare
  proxy_country: "us"
  humanlike: true
  block_consent_modals: true
  hybrid: true
  enable_live_url: false         # NEW: Enable LiveURL
```

## API Reference

### HybridBrowserFactory

#### Constructor Parameters

```python
HybridBrowserFactory(
    bql_endpoint: str,              # BrowserQL endpoint URL
    token: str,                     # Browserless API token
    proxy: Optional[str] = None,    # "residential" or "datacenter"
    proxy_country: Optional[str] = None,  # Country code (e.g., "us", "tr")
    humanlike: bool = True,         # Enable human-like behavior
    block_consent_modals: bool = True,    # Auto-dismiss cookie banners
    enable_live_url: bool = False,  # Enable LiveURL monitoring
)
```

#### Methods

##### `page(session_id: str, verify_cloudflare: bool = False) -> AsyncIterator[Page]`
Get or create a hybrid browser page.

**Parameters:**
- `session_id`: Unique identifier for the session
- `verify_cloudflare`: Whether to verify Cloudflare during initialization

**Returns:** Playwright Page object

**Example:**
```python
async with factory.page("my-session", verify_cloudflare=True) as page:
    await page.goto("https://example.com")
```

##### `get_live_url(session_id: str) -> Optional[str]`
Get the LiveURL for a session.

**Parameters:**
- `session_id`: The session ID

**Returns:** LiveURL string if available, None otherwise

**Example:**
```python
live_url = factory.get_live_url("my-session")
if live_url:
    print(f"Monitor at: {live_url}")
```

##### `wait_for_live_complete(session_id: str) -> None`
Wait for the LiveURL session to complete (user closes the LiveURL).

**Parameters:**
- `session_id`: The session ID to wait for

**Raises:** `ValueError` if session doesn't exist or CDP session is not available

**Example:**
```python
await factory.wait_for_live_complete("my-session")
print("User finished interacting!")
```

##### `screenshot(session_id: str, path: Optional[str] = None, full_page: bool = False) -> bytes`
Capture a screenshot of the session.

**Parameters:**
- `session_id`: The session ID
- `path`: Optional file path to save screenshot
- `full_page`: Whether to capture full scrollable page

**Returns:** Screenshot as bytes

**Example:**
```python
# Save to file
await factory.screenshot("my-session", path="screenshot.png")

# Get as bytes
screenshot_bytes = await factory.screenshot("my-session")
```

##### `close_session(session_id: str) -> None`
Close a specific session.

**Example:**
```python
await factory.close_session("my-session")
```

##### `close_all() -> None`
Close all sessions and Playwright instance.

**Example:**
```python
await factory.close_all()
```

## Examples

See `scripts/hybrid_example.py` for comprehensive examples:

1. **Basic Usage** - Simple navigation and screenshot
2. **Cloudflare Verification** - Automatic CAPTCHA solving
3. **LiveURL Monitoring** - Real-time session monitoring
4. **Complex Workflow** - Multi-step automation with error handling

Run examples:
```bash
# Edit the script to add your Browserless token
python scripts/hybrid_example.py
```

## Best Practices

### 1. Use Residential Proxy for Cloudflare
```python
factory = HybridBrowserFactory(
    proxy="residential",  # Required for Cloudflare
    proxy_country="us",
    # ...
)
```

### 2. Enable LiveURL for Debugging
```python
factory = HybridBrowserFactory(
    enable_live_url=True,  # Enable during development
    # ...
)
```

### 3. Capture Screenshots on Errors
```python
try:
    async with factory.page("my-session") as page:
        # Your automation
        pass
except Exception as e:
    # Capture error state
    await factory.screenshot("my-session", path="error.png")
    raise
```

### 4. Clean Up Sessions
```python
try:
    async with factory.page("my-session") as page:
        # Your automation
        pass
finally:
    await factory.close_all()
```

### 5. Use Session IDs Wisely
```python
# Good: Use meaningful session IDs
session_id = f"user-{user_id}-booking"

# Bad: Random IDs make debugging harder
session_id = str(uuid.uuid4())
```

## Cost Considerations

### LiveURL
- **Cost:** No additional cost
- **Benefit:** Real-time monitoring and debugging

### Cloudflare Verification
- **Cost:** Free (verify mutation doesn't incur units)
- **Requirement:** Residential proxy required
- **Benefit:** Automatic CAPTCHA solving

### Screenshots
- **Cost:** No additional cost (Playwright operation)
- **Benefit:** Visual debugging and proof of completion

### Session Timeout
- **Default:** 5 minutes (300,000ms)
- **Configurable:** Via BQL query parameters
- **Recommendation:** Set based on expected workflow duration

## Troubleshooting

### Issue: LiveURL not available

**Solution:**
1. Ensure `enable_live_url=True` in factory constructor
2. Check that CDP session was created successfully
3. Verify Browserless plan supports LiveURL

### Issue: Cloudflare verification fails

**Solution:**
1. Ensure `proxy="residential"` is set
2. Check proxy country matches target site
3. Verify Browserless token has residential proxy access
4. Check logs for verification result

### Issue: wait_for_live_complete hangs

**Solution:**
1. Ensure LiveURL was actually opened by user
2. Check CDP session is available
3. Set a timeout on the wait operation
4. Verify Browserless.liveComplete event is supported

### Issue: Screenshot fails

**Solution:**
1. Ensure session exists and is active
2. Check page is loaded and ready
3. Verify file path is writable
4. Try without full_page option first

## Migration Guide

### From Old Hybrid Implementation

**Before:**
```python
async with factory.page("my-session") as page:
    await page.goto("https://example.com")
    screenshot = await page.screenshot()
```

**After:**
```python
# Same API, but now with optional features
async with factory.page("my-session", verify_cloudflare=True) as page:
    # Get LiveURL if enabled
    live_url = factory.get_live_url("my-session")
    
    await page.goto("https://example.com")
    
    # Use factory screenshot method
    await factory.screenshot("my-session", path="screenshot.png")
```

### Key Changes
1. `page()` now accepts `verify_cloudflare` parameter
2. New `enable_live_url` constructor parameter
3. New methods: `get_live_url()`, `wait_for_live_complete()`, `screenshot()`
4. Improved error handling and logging
5. Better BQL mutation with reconnect

## References

- [BrowserQL Hybrid Guide](https://browserless.io/docs/hybrid)
- [Browserless.io Documentation](https://browserless.io/docs)
- [Playwright Documentation](https://playwright.dev)
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)

## See Also

- [Hybrid Browser Documentation](./hybrid-browser.md)
- [Architecture Guide](./architecture.md)
- [Main README](../README.md)

