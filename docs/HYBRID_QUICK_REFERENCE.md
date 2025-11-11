# BrowserQL Hybrid Mode - Quick Reference

## Basic Setup

```python
from agentbot.browser.hybrid import HybridBrowserFactory

factory = HybridBrowserFactory(
    bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
    token="YOUR_BROWSERLESS_TOKEN",
    proxy="residential",          # or "datacenter"
    proxy_country="us",           # optional
    humanlike=True,               # recommended
    block_consent_modals=True,    # recommended
    enable_live_url=False,        # set True for monitoring
)
```

## Basic Usage

```python
# Simple navigation
async with factory.page("session-id") as page:
    await page.goto("https://example.com")
    await factory.screenshot("session-id", path="screenshot.png")

# Cleanup
await factory.close_all()
```

## Feature Cheat Sheet

### 1. LiveURL Monitoring

```python
# Enable in constructor
factory = HybridBrowserFactory(..., enable_live_url=True)

# Get LiveURL
async with factory.page("session-id") as page:
    live_url = factory.get_live_url("session-id")
    print(f"Monitor at: {live_url}")
```

### 2. Wait for User Interaction

```python
async with factory.page("session-id") as page:
    # Get and share LiveURL
    live_url = factory.get_live_url("session-id")
    send_to_user(live_url)
    
    # Wait for user to finish
    await factory.wait_for_live_complete("session-id")
    
    # Continue automation
    print(f"User finished at: {page.url}")
```

### 3. Cloudflare Verification

```python
# Add verify_cloudflare=True to page() call
async with factory.page("session-id", verify_cloudflare=True) as page:
    # Cloudflare already solved!
    await page.goto("https://cloudflare-protected-site.com")
```

**Requirements:**
- Must use `proxy="residential"`
- Free (no unit costs)

### 4. Screenshot Capture

```python
# Viewport screenshot
await factory.screenshot("session-id", path="screenshot.png")

# Full page screenshot
await factory.screenshot(
    "session-id",
    path="full-page.png",
    full_page=True
)

# Get as bytes
screenshot_bytes = await factory.screenshot("session-id")
```

### 5. Session Management

```python
# Close specific session
await factory.close_session("session-id")

# Close all sessions
await factory.close_all()
```

## Common Patterns

### Pattern 1: Basic Automation

```python
factory = HybridBrowserFactory(...)

try:
    async with factory.page("session") as page:
        await page.goto("https://example.com")
        await page.fill("input[name='email']", "user@example.com")
        await page.click("button[type='submit']")
        await factory.screenshot("session", path="result.png")
finally:
    await factory.close_all()
```

### Pattern 2: With Cloudflare

```python
factory = HybridBrowserFactory(..., proxy="residential")

async with factory.page("session", verify_cloudflare=True) as page:
    await page.goto("https://protected-site.com")
    # Continue automation...
```

### Pattern 3: With LiveURL Monitoring

```python
factory = HybridBrowserFactory(..., enable_live_url=True)

async with factory.page("session") as page:
    live_url = factory.get_live_url("session")
    logger.info(f"Monitor at: {live_url}")
    
    # Do automation
    await page.goto("https://example.com")
```

### Pattern 4: Hybrid Bot + Human

```python
factory = HybridBrowserFactory(..., enable_live_url=True)

async with factory.page("session") as page:
    # Bot does initial setup
    await page.goto("https://example.com/login")
    await page.fill("input[name='email']", "user@example.com")
    
    # User completes sensitive steps
    live_url = factory.get_live_url("session")
    send_email(user, f"Complete login at: {live_url}")
    await factory.wait_for_live_complete("session")
    
    # Bot continues
    await page.goto("https://example.com/dashboard")
```

### Pattern 5: Error Handling

```python
factory = HybridBrowserFactory(...)

try:
    async with factory.page("session") as page:
        await page.goto("https://example.com")
        # ... automation ...
except Exception as e:
    logger.error(f"Error: {e}")
    # Capture error state
    try:
        await factory.screenshot("session", path="error.png")
    except:
        pass
finally:
    await factory.close_all()
```

## Configuration

### Environment Variables

```bash
export BROWSERQL_HYBRID=true
export BROWSERQL_TOKEN=your-token
export BROWSERQL_ENABLE_LIVE_URL=true
```

### YAML Config

```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-token"
  proxy: "residential"
  proxy_country: "us"
  humanlike: true
  block_consent_modals: true
  hybrid: true
  enable_live_url: false
```

## API Quick Reference

### Constructor

```python
HybridBrowserFactory(
    bql_endpoint: str,              # Required
    token: str,                     # Required
    proxy: Optional[str] = None,    # "residential" or "datacenter"
    proxy_country: Optional[str] = None,  # e.g., "us", "tr"
    humanlike: bool = True,
    block_consent_modals: bool = True,
    enable_live_url: bool = False,
)
```

### Methods

```python
# Get page (context manager)
async with factory.page(
    session_id: str,
    verify_cloudflare: bool = False
) -> Page:
    ...

# Get LiveURL
live_url = factory.get_live_url(session_id: str) -> Optional[str]

# Wait for LiveURL completion
await factory.wait_for_live_complete(session_id: str) -> None

# Capture screenshot
await factory.screenshot(
    session_id: str,
    path: Optional[str] = None,
    full_page: bool = False
) -> bytes

# Close session
await factory.close_session(session_id: str) -> None

# Close all sessions
await factory.close_all() -> None
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Install playwright for hybrid mode" | Run `pip install playwright && playwright install` |
| LiveURL not available | Set `enable_live_url=True` |
| Cloudflare verification fails | Use `proxy="residential"` |
| Screenshot fails | Ensure session exists and page is loaded |
| Session timeout | Default is 5 minutes |

## Cost Reference

| Feature | Cost | Notes |
|---------|------|-------|
| LiveURL | Free | No additional cost |
| Cloudflare Verification | Free | verify mutation is free |
| Screenshots | Free | Playwright operation |
| CDP Session | Free | Included with BQL |

## Best Practices

1. ✅ Use `proxy="residential"` for Cloudflare
2. ✅ Enable `humanlike=True` for bot detection
3. ✅ Use `block_consent_modals=True` for cookie banners
4. ✅ Capture screenshots on errors
5. ✅ Always call `close_all()` in finally block
6. ✅ Use meaningful session IDs
7. ✅ Enable LiveURL during development
8. ✅ Handle exceptions properly

## Examples

See `scripts/hybrid_example.py` for complete examples:

```bash
python scripts/hybrid_example.py
```

## Documentation

- **Complete Guide:** `docs/HYBRID_FEATURES.md`
- **Integration:** `docs/hybrid-browser.md`
- **Upgrade Guide:** `HYBRID_UPGRADE_SUMMARY.md`
- **Examples:** `scripts/hybrid_example.py`

## Support

1. Check `docs/HYBRID_FEATURES.md` for detailed documentation
2. Review `scripts/hybrid_example.py` for working examples
3. Check error logs for detailed information
4. Visit [Browserless.io Documentation](https://browserless.io/docs)

---

**Quick Links:**
- [Complete Documentation](./HYBRID_FEATURES.md)
- [Example Script](../scripts/hybrid_example.py)
- [Upgrade Guide](../HYBRID_UPGRADE_SUMMARY.md)
- [Browserless.io](https://browserless.io)

