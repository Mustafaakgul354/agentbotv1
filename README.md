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

## Key Modules

- `src/agentbot/core/` – runtime orchestration, message bus, settings, and state planner.
- `src/agentbot/agents/` – base classes plus default monitor/booking agent logic.
- `src/agentbot/services/` – HTTP client, email inbox, form filler, and example site providers.
- `src/agentbot/data/session_store.py` – JSON-backed session store; swap with your DB as needed.

## Running Multiple Agents

Each session in the store spawns its own monitor and booking agents. The monitor publishes `appointment.available` events; the booking agent consumes them and attempts to complete the reservation. Add more sessions to scale horizontally. For distributed deployments, replace the in-memory bus and session store with shared infrastructure (Redis, Postgres, etc.) and containerise the runtime.

## Testing & Extensibility

- Add unit tests under `tests/` to exercise provider logic and state machine transitions.
- Enable linting by running `ruff check .` and `pytest` once you add tests.
- Implement backoff, rate-limiting, and CAPTCHA handling according to the target site's policies.

## Security Notes

- Store secrets (API keys, passwords) securely—consider using a secrets manager and encrypting `session_store.json`.
- Respect the target website's terms of service and rate limits.
- Avoid logging sensitive personal data; redact values before emission.

