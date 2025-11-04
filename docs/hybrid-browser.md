# Hybrid Browser Mode: BQL + Playwright

## Overview

**Hybrid Mode** combines the best of two approaches:
- **BQL (BrowserQL)** for stealth and security (CAPTCHA solving, proxy rotation, anti-detection)
- **Playwright** for flexibility and powerful automation API

This mode initializes a browser session with BQL's stealth features, then connects Playwright to the same browser via Chrome DevTools Protocol (CDP), giving you both capabilities in one session.

## How It Works

### Initialization Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. BQL Session Initialization                                  │
│    - Navigate to about:blank with stealth parameters            │
│    - Detect and solve Cloudflare CAPTCHA if present             │
│    - Apply residential proxy rotation if configured             │
│    - Enable humanlike behavior                                  │
│    - Auto-handle consent modals                                 │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Get browserWSEndpoint from BQL                               │
│    - Query /chrome/json/version endpoint                        │
│    - Retrieve WebSocket debugger URL                            │
│    - Fallback: construct endpoint manually if needed            │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Connect Playwright via CDP                                   │
│    - chromium.connectOverCDP(browserWSEndpoint)                 │
│    - Reuse existing context and page                            │
│    - Ready for Playwright operations                            │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Agent Operations                                             │
│    - Navigate, fill, click using Playwright API                 │
│    - Take screenshots, extract content                          │
│    - All protected by BQL's stealth layer                       │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration

### Via YAML Config

```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-browserless-token"
  proxy: "residential"           # or "datacenter"
  proxy_country: "tr"            # optional country code
  humanlike: true                # human-like mouse/keyboard
  block_consent_modals: true     # auto-dismiss cookie banners
  hybrid: true                   # ENABLE HYBRID MODE
```

### Via Environment Variables

```bash
# Enable hybrid mode
export BROWSERQL_HYBRID=true

# Set token
export BROWSERQL_TOKEN=your-browserless-token
```

### Usage in Code

The system automatically detects and uses `HybridBrowserFactory` when configured:

```python
# In scripts/run_agents.py or src/agentbot/app/main.py
# When hybrid: true or BROWSERQL_HYBRID=true, HybridBrowserFactory is used

async with browser.page(session_id) as page:
    # This page is now:
    # - Connected to BQL's stealth-initialized browser
    # - Controlled via Playwright's full API
    await page.goto("https://example.com")
    await page.fill("input[name='email']", "user@example.com")
    await page.click("button[type='submit']")
    screenshot = await page.screenshot()
```

## Advantages

### Stealth (from BQL)
✅ Residential proxy rotation  
✅ CAPTCHA solving (Cloudflare, hCaptcha, etc.)  
✅ Humanlike behavior (mouse movement, typing speed)  
✅ Cookie/consent modal handling  
✅ Reduced fingerprinting  

### Flexibility (from Playwright)
✅ Rich automation API  
✅ Screenshot/PDF generation  
✅ Multiple contexts and pages  
✅ Network interception  
✅ Complex selectors (CSS, XPath, Playwright locators)  
✅ Session persistence via cookies  

## Cost Considerations

### Hybrid Mode Costs

| Operation | Cost |
|-----------|------|
| BQL session init (CAPTCHA solving) | ~1 unit (no cost if no CAPTCHA) |
| Playwright operations | Normal Playwright rates |
| Total per session | Lower than expected due to BQL no-cost verification |

**Example:** If you initialize 100 sessions and 20% hit CAPTCHA:
- 20 BQL sessions with CAPTCHA solving: 20 units
- 80 BQL sessions without CAPTCHA: 0 units
- All Playwright operations: Standard rates

### Pure BQL Mode (for comparison)
- Every operation costs units
- No flexibility of Playwright API

## Real-World Example: VFS Appointment Booking

```python
async def book_appointment(browser, session_id, appointment_slot):
    async with browser.page(session_id) as page:
        # ✅ Stealth: BQL already handled CAPTCHA during init
        # ✅ Flexible: Playwright controls the booking flow
        
        # Navigate (via Playwright, protected by BQL stealth)
        await page.goto("https://visa.vfsglobal.com/tur/en/fra/login")
        
        # Fill login form
        await page.fill("#Email", credentials["username"])
        await page.fill("#Password", credentials["password"])
        await page.click("button:has-text('Sign In')")
        
        # Wait for navigation (Playwright feature)
        await page.wait_for_url("**/dashboard", timeout=30000)
        
        # Navigate to booking page
        await page.goto("https://visa.vfsglobal.com/tur/en/fra/book-appointment")
        
        # Book the slot
        await page.click(f"button[data-slot='{appointment_slot.id}']")
        await page.click("button:has-text('Confirm')")
        
        # Capture proof (Playwright feature)
        screenshot = await page.screenshot(path=f"booking_{session_id}.png")
        
        return {"success": True, "proof": screenshot}
```

## Troubleshooting

### Issue: "Failed to get browserWSEndpoint"

**Solution:** The BQL endpoint might not support CDP. Check:
1. Browserless.io plan supports CDP
2. Endpoint is correct: `https://production-sfo.browserless.io/chrome/bql`
3. Token is valid

### Issue: "Cannot connect over CDP"

**Solution:** The WebSocket connection might be blocked:
1. Check firewall/proxy settings
2. Ensure BROWSERQL_HYBRID is set before session creation
3. Check logs for the actual WebSocket URL

### Issue: "Cloudflare challenge not solved"

**Solution:** 
1. Ensure `proxy: residential` is set (required for Cloudflare)
2. Check that `verify(type: "cloudflare")` completes successfully
3. Try with `humanlike: true` for better success rate

## Advanced: Manual Hybrid Setup

If you need to customize behavior, you can use `HybridBrowserFactory` directly:

```python
from agentbot.browser.hybrid import HybridBrowserFactory

# Create factory
factory = HybridBrowserFactory(
    bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
    token="your-token",
    proxy="residential",
    proxy_country="tr",
    humanlike=True,
    block_consent_modals=True,
)

# Use it
async with factory.page("session-1") as page:
    # Your code here
    pass

# Cleanup
await factory.close_all()
```

## Best Practices

1. **Set residential proxy** for sites that block datacenter IPs
2. **Enable humanlike** for sites with bot detection
3. **Use block_consent_modals** to auto-dismiss cookie banners
4. **Cache sessions** - HybridFactory maintains persistent sessions per session_id
5. **Monitor costs** - Track actual vs. expected unit usage

## Comparison: All Browser Modes

| Feature | Playwright | BrowserQL | Hybrid |
|---------|-----------|-----------|--------|
| CAPTCHA solving | ❌ | ✅ | ✅ |
| Residential proxy | ❌ | ✅ | ✅ |
| Rich API | ✅ | ❌ | ✅ |
| Screenshots | ✅ | ❌ | ✅ |
| Cost effective | ✅ | ❌ | ✅ |
| Easy setup | ✅ | ✅ | ✅ |
| **Recommended** | Local dev | REST API only | Production |

## See Also

- [BrowserQL Documentation](https://browserless.io/blog/announcing-browserql)
- [Playwright Documentation](https://playwright.dev)
- [Main README](./README.md)
- [Architecture Guide](./architecture.md)
