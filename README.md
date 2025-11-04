# AgentBot – Multi-Agent Appointment Booking

AgentBot is a Python framework for building coordinated monitor/booking agents that secure scarce appointment slots on high-demand portals. Each user session is handled by a pair of asynchronous agents:

- **MonitorAgent** keeps an authenticated session alive and polls for openings.
- **BookingAgent** reacts to availability events, retrieves OTP/verification codes, fills forms, and confirms the booking.

Agents communicate through an in-memory message bus by default; adapters make it easy to swap in Redis or another broker when scaling out.

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -e .
   playwright install  # optional, only if you provide a Playwright-based provider
   ```

2. **Prepare configuration**
   - Copy `config/runtime.example.yml` to `config/runtime.yml` and adjust endpoints, email inbox credentials, and paths.
   - Populate `config/session_store.example.json` with one entry per user session (credentials + profile data) and point `session_store_path` in the runtime config to the file you maintain.
   - (Optional) Update `config/form_mapping.example.yml` with CSS selectors for the booking form inputs if you use a headless browser to submit forms.
   - (Recommended) Generate a Fernet key with `python - <<'PY'\nfrom cryptography.fernet import Fernet\nprint(Fernet.generate_key().decode())\nPY` and export it as `AGENTBOT_SESSION_KEY` to encrypt your session store at rest.

3. **Choose browser backend** (Playwright or BrowserQL)
   - **Playwright** (default): Install playwright browsers with `playwright install`
   - **BrowserQL**: Configure BrowserQL settings in `config/runtime.yml` or use environment variables (see below)

4. **Run the runtime**
   ```bash
   python scripts/run_agents.py --config config/runtime.yml
   ```

The CLI spins up monitor/booking agents for every session in your store and runs them until interrupted.

## Optional: Enable BrowserQL (Browserless.io)

To use BrowserQL instead of Playwright for browser automation, configure BrowserQL settings in your `config/runtime.yml`:

```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-browserless-token"  # or use BROWSERQL_TOKEN env var
  proxy: "residential"  # optional: "residential" or "datacenter"
  proxy_country: "tr"  # optional: country code for proxy
  humanlike: true  # optional: enable human-like behavior
  block_consent_modals: true  # optional: auto-handle consent modals
```

Or use environment variables:
```env
BROWSERQL_TOKEN=your-browserless-token
```

When BrowserQL is configured, agents will use it instead of Playwright. BrowserQL provides better stealth capabilities and avoids fingerprinting.

### Hybrid Mode: Combine BQL Stealth with Playwright Flexibility

For maximum capability, enable **Hybrid Mode** which combines BQL's stealth features (CAPTCHA solving, proxy rotation, human-like behavior) with Playwright's powerful automation API:

```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-browserless-token"
  proxy: "residential"
  proxy_country: "tr"
  humanlike: true
  block_consent_modals: true
  hybrid: true  # Enable hybrid mode
```

**How Hybrid Mode Works:**
1. **BQL Session**: Initializes browser with stealth (CAPTCHA solving, proxy rotation, humanlike behavior)
2. **Playwright Connect**: Connects Playwright via CDP (chromium.connectOverCDP) to the BQL browser
3. **Best of Both**: Get BQL's stealth + Playwright's rich API (screenshots, complex selectors, etc.)

Or enable via environment variable:
```env
export BROWSERQL_HYBRID=true
export BROWSERQL_TOKEN=your-browserless-token
```

**Cost Note:** Hybrid mode uses one session for initialization (CAPTCHA solving) plus normal Playwright operations.

#### Hybrid Mode Advantages

**From BQL (Stealth):**
- ✅ **Residential Proxy Rotation** – Avoid datacenter IP blocks
- ✅ **CAPTCHA Solving** – Auto-solve Cloudflare, hCaptcha, reCAPTCHA
- ✅ **Anti-Detection** – Humanlike mouse/keyboard behavior, reduced fingerprinting
- ✅ **Consent Handling** – Auto-dismiss cookie/consent modals
- ✅ **No Local Browser** – Leverage Browserless.io's infrastructure

**From Playwright (Flexibility):**
- ✅ **Rich API** – Complex selectors (CSS, XPath, Playwright locators)
- ✅ **Screenshots & PDF** – Visual proof of booking, debugging
- ✅ **Multiple Contexts** – Isolate sessions without separate browsers
- ✅ **Network Interception** – Monitor, modify, or mock API calls
- ✅ **Session Persistence** – Automatic cookie/storage management
- ✅ **Local Testing** – Develop locally before deploying to Browserless.io

#### Choosing Your Browser Mode

| Feature | Playwright | BrowserQL | **Hybrid** |
|---------|-----------|-----------|-----------|
| **CAPTCHA Solving** | ❌ | ✅ | ✅ |
| **Residential Proxy** | ❌ | ✅ | ✅ |
| **Rich Playwright API** | ✅ | ❌ | ✅ |
| **Screenshots/PDF** | ✅ | ❌ | ✅ |
| **Local Development** | ✅ | ❌ | ✅ |
| **Cost Efficient** | ✅ | ⚠️ (high volume ops) | ✅ |
| **Recommended For** | Local dev, testing | REST API only | Production with detection |

#### Real Example: VFS Appointment Booking

```python
# With Hybrid Mode, agents automatically get:
async with browser.page(session_id) as page:
    # ✅ Stealth: Already handled CAPTCHA during session init
    # ✅ Flexible: Full Playwright API available
    
    # Navigate (protected by BQL's stealth)
    await page.goto("https://visa.vfsglobal.com/tur/en/fra/login")
    
    # Fill and submit login
    await page.fill("#Email", credentials["username"])
    await page.fill("#Password", credentials["password"])
    await page.click("button:has-text('Sign In')")
    
    # Wait for dashboard (Playwright feature)
    await page.wait_for_url("**/dashboard")
    
    # Book appointment
    await page.click("button[data-slot='available']")
    await page.click("button:has-text('Confirm')")
    
    # Capture proof (Playwright feature)
    screenshot = await page.screenshot(path=f"booking_{session_id}.png")
```

#### Troubleshooting Hybrid Mode

**Problem: "Failed to get browserWSEndpoint"**
```bash
# Solution: Verify Browserless.io plan and endpoint
- Check your Browserless.io plan supports Chrome API
- Verify endpoint: https://production-sfo.browserless.io/chrome/bql
- Ensure token is valid and active
```

**Problem: "Cannot connect over CDP"**
```bash
# Solution: Check network connectivity and configuration
export BROWSERQL_HYBRID=true
export BROWSERQL_TOKEN=your-valid-token
# Check logs for actual WebSocket URL being used
```

**Problem: "Cloudflare challenge not detected/solved"**
```bash
# Solution: Residential proxy required for Cloudflare
browserql:
  proxy: "residential"    # MUST be residential, not datacenter
  proxy_country: "tr"     # Optional, helps with geo-specific sites
  humanlike: true         # Improves detection success
```

#### More Information

See [`docs/hybrid-browser.md`](./docs/hybrid-browser.md) for:
- Detailed initialization flow and architecture
- Advanced configuration options
- Cost analysis and examples
- Manual setup guide
- Best practices and performance tips

## Optional: Enable LLM (OpenAI)

Set these variables (for Docker, place them in your `.env`):

```env
AGENTBOT_LLM=openai
OPENAI_API_KEY=sk-...
# Optional model override
OPENAI_MODEL=gpt-4o-mini
```

When enabled, the runtime will initialise an OpenAI client and use it in the VFS availability flow as a fallback classification step (to understand pages that explicitly state that no appointments are available). The system continues to work without an LLM.

## Customising Providers

The sample `ExampleAvailabilityProvider` and `ExampleBookingProvider` in `src/agentbot/services/site_provider.py` illustrate how to integrate a website using JSON APIs plus IMAP for OTP retrieval. For real-world usage you will typically:

- Replace HTTP polling with Playwright/selenium automation if availability is only visible in rendered pages.
- Implement login flows that store session cookies/tokens in `HttpClient`.
- Extend `ExampleBookingProvider.book` to drive the booking UI, use `FormFiller` to populate fields, and handle CAPTCHA or additional validation steps.
- Persist audit logs and booking outcomes to your observability stack.

Both providers conform to lightweight protocols defined in `MonitorAgent` / `BookingAgent`, so you can plug in alternative implementations without touching the runtime.

## Observability & Audit Trail

- Heartbeats are emitted as `agent.heartbeat` events after every poll cycle, allowing external monitors to track agent liveness.
- Booking outcomes are captured by the `AuditLogger` and written as JSON Lines (default location: `artifacts/audit.log`). Set `AGENTBOT_AUDIT_LOG` to override the path.

## Key Modules

- `src/agentbot/core/` – runtime orchestration, message bus, settings, and state planner.
- `src/agentbot/agents/` – base classes plus default monitor/booking agent logic.
- `src/agentbot/services/` – HTTP client, email inbox, form filler, audit logger, and site providers.
- `src/agentbot/data/session_store.py` – JSON-backed (optionally Fernet-encrypted) session store; swap with your DB as needed.

## Running Multiple Agents

Each session in the store spawns its own monitor and booking agents. The monitor publishes `appointment.available` events; the booking agent consumes them and attempts to complete the reservation. Add more sessions to scale horizontally. For distributed deployments, replace the in-memory bus and session store with shared infrastructure (Redis, Postgres, etc.) and containerise the runtime.

## Testing & Extensibility

- Add unit tests under `tests/` to exercise provider logic and state machine transitions.
- Enable linting by running `ruff check .` and `pytest` once you add tests.
- Implement backoff, rate-limiting, and CAPTCHA handling according to the target site's policies.

## Security Notes

- Store secrets (API keys, passwords) securely—set `AGENTBOT_SESSION_KEY` so the bundled session store encrypts data at rest, or replace it with your own backend.
- Respect the target website's terms of service and rate limits.
- Avoid logging sensitive personal data; redact values before emission.
