# Multi-Agent Appointment Booking Architecture

## Goals
- Continuously monitor appointment availability for multiple user sessions.
- Automatically claim and book appointments when they appear.
- Isolate each user's session while enabling coordinated booking actions.
- Provide extensible abstractions for integrating different appointment websites.

## High-Level Components

### 1. Agent Runtime
- `AgentRuntime` orchestrates agent lifecycles.
- Uses an `asyncio` event loop to run agents concurrently.
- Maintains a registry of session agents (`MonitorAgent`) and booking agents (`BookingAgent`).
- Provides message routing (via an in-memory pub/sub bus) and shared services (e.g., logging, persistence).

### 2. Message Bus
- `MessageBus` exposes asynchronous publish/subscribe channels.
- Messages encapsulate event type, metadata, and payload.
- Monitor agents publish `AppointmentAvailable` events.
- Booking agents subscribe to relevant events (filtered by user/session IDs).
- Future extension: plug in Redis, RabbitMQ, or Kafka for horizontal scaling.

### 3. Session Store
- `SessionStore` persists user-specific data:
  - Credentials / personal info (stored encrypted at rest).
  - Appointment preferences.
  - Current session tokens and CSRF values.
- Reference implementation uses an encrypted JSON file; interface allows DB backends.

### 4. MonitorAgent (Per-User)
- Encapsulates a single user's session with the target website.
- Periodically polls availability using authenticated requests or headless browser automation.
- Implements:
  - `login_if_needed()`
  - `check_availability()`
  - `heartbeat()` (implemented via `EventType.HEARTBEAT` events for metrics & observability)
- On detecting availability, publishes an `AppointmentAvailable` message with session context.

### 5. BookingAgent (Per-User)
- Listens for availability events for its user.
- Steps:
  1. Fetches user profile & preferences from `SessionStore`.
  2. Navigates to booking flow using existing session cookies or tokens.
  3. Triggers verification (if required), pulls the email code via `EmailInboxService`.
  4. Completes form fields per uploaded data (`FormFiller` helper).
  5. Submits booking and verifies completion via DOM parsing or API response.
- Emits `BookingResult` events (success/failure) for downstream alerting.

### 6. Services
- `EmailInboxService`: pluggable provider to read verification codes (IMAP, API).
- `HttpClient` / `BrowserClient`: wrapper around `httpx`, `requests`, or Playwright.
- `FormFiller`: maps schema definitions to DOM selectors.
- `AuditLogger`: structured logs for observability & replay (JSON Lines stored under `artifacts/` by default).
- **`HybridBrowserFactory`** (optional): combines BQL stealth features (CAPTCHA solving, proxy rotation) with Playwright's powerful automation API via Chrome DevTools Protocol (CDP).

### 7. Planning & Scheduling
- `AgentPlanner` coordinates retries, backoff, and appointment preference prioritisation.
- Maintains per-session finite-state machine (FSM) covering states:
  - `Idle` → `Monitoring` → `Claiming` → `Booking` → `Booked` / `Failed`
- FSM ensures resumed agents recover safely after restarts.

## Browser Selection

The system supports three browser automation modes, selectable via configuration:

| Mode | Factory | Use Case | Key Features |
|------|---------|----------|--------------|
| **Playwright** | `BrowserFactory` | Local dev, testing | Direct browser control, full API |
| **BrowserQL** | `BrowserQLFactory` | REST/GraphQL API only | Stealth (CAPTCHA solving, proxy), no local browser |
| **Hybrid** (recommended) | `HybridBrowserFactory` | Production sites with detection | BQL stealth initialization + Playwright control via CDP |

### Hybrid Mode Details

The hybrid mode initializes a browser session with BQL's stealth features (CAPTCHA solving, proxy rotation, humanlike behavior), then connects Playwright via Chrome DevTools Protocol (CDP) for rich automation:

```
BQL Session Init (Stealth)
        ↓
Get browserWSEndpoint
        ↓
chromium.connectOverCDP(endpoint)
        ↓
Playwright Control (Full API)
```

This combines:
- **BQL advantages**: residential proxies, CAPTCHA solving, anti-detection
- **Playwright advantages**: screenshots, complex selectors, network interception, flexibility

Enabled via config:
```yaml
browserql:
  endpoint: "https://production-sfo.browserless.io/chrome/bql"
  token: "your-token"
  hybrid: true
```

## Data Flow
1. `AgentRuntime` boots, loads user sessions from configuration.
2. For each user, instantiate a `MonitorAgent` & `BookingAgent`.
3. Monitor agent logs in (if needed) and enters a polling loop.
4. When availability detected:
   - Monitor agent publishes `AppointmentAvailable` with session identifier & slot details.
5. Booking agent receives event, locks the slot by quickly triggering the booking flow.
6. Booking agent retrieves OTP via `EmailInboxService`, enters code, populates forms, and submits.
7. Booking agent publishes `BookingResult`; runtime logs and optionally notifies user.

## Security & Compliance Considerations
- Store secrets encrypted; the session store encrypts records with Fernet when `AGENTBOT_SESSION_KEY` is configured.
- Rate-limit requests; conform to website's terms of service.
- Use rotating proxies or IP pools cautiously and lawfully.
- Audit trail for bookings and agent actions.
- Implement CAPTCHA solving with appropriate user consent or manual fallback.

## Extensibility
- Define abstract base classes (`BaseMonitorAgent`, `BaseBookingAgent`) for new websites.
- Use dependency injection for services to simplify testing.
- Provide CLI & API surfaces for runtime operations (start/stop agents, inspect status).

## Deployment Topology
- Local single-process prototype (current repo).
- Scale-out option: containerise agents, deploy to Kubernetes with shared Redis message bus and Postgres session store.
- Observability via OpenTelemetry exporters (traces, metrics).

## VFS Global Provider
The Playwright-based provider for VFS TR/EN/FRA lives at `agentbot/site/vfs_fra_flow.py`. It encapsulates:
- Login (email/password → OTP via IMAP)
- Navigation to `application-detail` and `book-appointment`
- DOM-based slot probing and booking interaction
