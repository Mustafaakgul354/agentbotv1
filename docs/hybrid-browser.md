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
  enable_live_url: false         # Enable LiveURL for monitoring (optional)
```

### Via Environment Variables

```bash
# Enable hybrid mode
export BROWSERQL_HYBRID=true

# Set token
export BROWSERQL_TOKEN=your-browserless-token

# Enable LiveURL (optional)
export BROWSERQL_ENABLE_LIVE_URL=true
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

### Advanced Features
✅ LiveURL support for monitoring and debugging  
✅ CDP (Chrome DevTools Protocol) session access  
✅ Wait for LiveURL completion (user interaction)  
✅ Real-time session monitoring  
✅ Screenshot capture with full-page support  

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
        await page.goto("https://visa.vfsglobal.com/tur/tr/fra/login", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_selector("xpath=//div[contains(text(), 'Başarılı!')]", timeout=5000)
        
        # Fill login form (with proper timeout and fallbacks)
        await page.fill("xpath=//input[@id='Email']", credentials["username"])
        await page.fill("xpath=//input[@id='Password']", credentials["password"])
        await page.click("xpath=//button[normalize-space(text())='Oturum Aç']")
        
        # Wait for navigation (Playwright feature)
        await page.wait_for_url("**/dashboard", timeout=30000)
        
        # Navigate to booking page
        await page.goto("https://visa.vfsglobal.com/tur/tr/fra/book-appointment")
        
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

## Hybrid Mode: Connect Puppeteer or Playwright Manually

BrowserQL can hand you a ready-to-use Chrome DevTools endpoint through the `reconnect` mutation. Run the following operation against your `/chrome/bql` endpoint (same token/proxy params you provide to the factory):

```graphql
mutation HybridSession {
  goto(url: "https://example.com") {
    status
  }

  reconnect(timeout: 30000) {
    browserWSEndpoint
  }
}
```

Then plug the returned `browserWSEndpoint` into any CDP client:

```python
from playwright.async_api import async_playwright

async with async_playwright() as pw:
    browser = await pw.chromium.connect_over_cdp(browserWSEndpoint)
    page = browser.contexts[0].pages[0]
```

```ts
import puppeteer from "puppeteer";

const browser = await puppeteer.connect({ browserWSEndpoint });
const page = await browser.newPage();
```

`HybridBrowserFactory` now performs this sequence internally, so your AgentBot codebase gets the same behavior automatically—use the snippet above only if you need to script BrowserQL from another tool.

## Advanced Features

### LiveURL Support

LiveURL allows you to monitor and interact with browser sessions in real-time. This is particularly useful for:
- Debugging automation flows
- Allowing end-users to interact with the browser
- Monitoring session progress
- Manual intervention when needed

#### Enable LiveURL

```python
from agentbot.browser.hybrid import HybridBrowserFactory

factory = HybridBrowserFactory(
    bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
    token="your-token",
    proxy="residential",
    proxy_country="us",
    humanlike=True,
    block_consent_modals=True,
    enable_live_url=True,  # Enable LiveURL
)

async with factory.page("my-session") as page:
    # LiveURL is automatically logged when session is created
    live_url = factory.get_live_url("my-session")
    print(f"Monitor session at: {live_url}")
    
    # Navigate and perform actions
    await page.goto("https://example.com")
    
    # Your automation code here...
```

#### Wait for LiveURL Completion

You can wait for an end-user to finish interacting via LiveURL before continuing automation:

```python
async with factory.page("my-session") as page:
    # Get LiveURL
    live_url = factory.get_live_url("my-session")
    
    # Share LiveURL with end-user (email, SMS, display in UI, etc.)
    print(f"Please complete the task at: {live_url}")
    
    # Wait for user to finish (closes LiveURL)
    await factory.wait_for_live_complete("my-session")
    
    # Continue automation after user is done
    print(f"User finished! Final URL: {page.url}")
    
    # Capture final state
    await factory.screenshot("my-session", path="final-state.png")
```

### Cloudflare Verification

Automatically verify Cloudflare challenges during session initialization:

```python
# Initialize session with Cloudflare verification
async with factory.page("my-session", verify_cloudflare=True) as page:
    # Cloudflare challenge is automatically solved during initialization
    # Navigate to Cloudflare-protected site
    await page.goto("https://cloudflare-protected-site.com")
    
    # Continue with automation...
```

**Requirements:**
- Residential proxy must be enabled (`proxy="residential"`)
- Cloudflare verification does not incur unit costs (free with BQL)

### Screenshot Capture

Capture screenshots at any point during automation:

```python
# Capture current viewport
screenshot_bytes = await factory.screenshot("my-session")

# Save to file
await factory.screenshot("my-session", path="screenshot.png")

# Capture full scrollable page
await factory.screenshot(
    "my-session",
    path="full-page.png",
    full_page=True
)
```

### CDP Session Access

For advanced use cases, you can access the CDP session directly:

```python
async with factory.page("my-session") as page:
    # CDP session is automatically created and stored
    # Access it from the internal session storage if needed
    
    # Example: Listen to custom CDP events
    # (This is handled internally by wait_for_live_complete)
    pass
```

## Advanced: Manual Hybrid Setup

If you need to customize behavior, you can use `HybridBrowserFactory` directly:

```python
from agentbot.browser.hybrid import HybridBrowserFactory

# Create factory with all options
factory = HybridBrowserFactory(
    bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
    token="your-token",
    proxy="residential",
    proxy_country="tr",
    humanlike=True,
    block_consent_modals=True,
    enable_live_url=True,  # Enable LiveURL monitoring
)

# Use it with Cloudflare verification
async with factory.page("session-1", verify_cloudflare=True) as page:
    # Your code here
    await page.goto("https://example.com")
    
    # Capture screenshot
    await factory.screenshot("session-1", path="screenshot.png")

# Cleanup
await factory.close_all()
```

### Complete Example

See `scripts/hybrid_example.py` for comprehensive examples including:
- Basic usage
- Cloudflare verification
- LiveURL monitoring
- Complex multi-step workflows
- Error handling and screenshots

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
