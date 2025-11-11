# AI-Powered Form Filling

## Overview

The AI-powered form filling feature uses Large Language Models (LLM) to automatically analyze web page structure, identify form fields, and fill them with the correct data in the proper sequence. This eliminates the need for hardcoded selectors and makes the system adaptable to page changes.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Navigate to Page                                             │
│    - Load the target URL (e.g., VFS login page)                 │
│    - Wait for page to fully load (networkidle)                  │
│    - Handle Cloudflare/Turnstile if present                     │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Extract HTML Content                                          │
│    - Get full page HTML                                          │
│    - Extract form-related elements (forms, inputs, buttons)     │
│    - Reduce size for token efficiency                           │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. AI Analysis                                                   │
│    - Send HTML to LLM (GPT-4o-mini)                             │
│    - LLM identifies form fields and their purposes              │
│    - LLM creates action sequence (fill → click → wait)          │
│    - Returns structured JSON with selectors and metadata        │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Map Session Data to Fields                                   │
│    - Match field purposes to session data                       │
│    - email → credentials.username                               │
│    - password → credentials.password                            │
│    - first_name → profile.first_name                            │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Execute Action Sequence                                       │
│    - Fill fields in correct order                               │
│    - Click buttons as needed                                    │
│    - Wait between actions (human-like behavior)                 │
│    - Handle OTP if required                                     │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Verify Success                                                │
│    - Check for navigation to success page                       │
│    - Capture screenshots for debugging                          │
│    - Fall back to manual selectors if AI fails                 │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

```bash
# OpenAI API Key (required)
export OPENAI_API_KEY="sk-..."

# Optional: Email configuration for OTP
export EMAIL_HOST="imap.gmail.com"
export EMAIL_PORT="993"
export EMAIL_USERNAME="your-email@gmail.com"
export EMAIL_PASSWORD="your-app-password"
```

### YAML Configuration

Add to `config/runtime.yml`:

```yaml
llm:
  provider: "openai"
  # api_key loaded from OPENAI_API_KEY env var
  model: "gpt-4o-mini"
  enable_page_analysis: true
  temperature: 0.1  # Low for consistent results
```

## Usage

### Basic Usage with VFS Login

```python
from pathlib import Path
from agentbot.browser.play import BrowserFactory
from agentbot.data.session_store import SessionStore
from agentbot.services.llm import OpenAIClient
from agentbot.services.email import EmailInboxService
from agentbot.site.vfs_fra_flow import VfsAvailabilityProvider

# Create LLM client
llm = OpenAIClient(
    api_key="your-api-key",
    model="gpt-4o-mini"
)

# Create browser
browser = BrowserFactory(
    headless=False,
    user_data_root=Path(".user_data")
)

# Create email service
email_service = EmailInboxService(
    host="imap.gmail.com",
    port=993,
    username="your-email@gmail.com",
    password="your-password",
    folder="INBOX",
    use_ssl=True
)

# Load session store (for fresh data on each login)
session_store = SessionStore(Path("config/session_store.json"))

# Create provider with AI enabled
provider = VfsAvailabilityProvider(
    browser,
    email_service=email_service,
    llm=llm,
    enable_ai_form_filling=True,  # Enable AI!
    session_store=session_store,  # Fresh data on each login
)

# Login will now use AI to analyze and fill the form
# Session data is re-read fresh each time
await provider.ensure_login(session)
```

### Using PageAnalyzer Directly

```python
from agentbot.services.llm import OpenAIClient
from agentbot.services.page_analyzer import PageAnalyzer

# Create analyzer (cache disabled for fresh analysis each time)
llm = OpenAIClient(api_key="your-key")
analyzer = PageAnalyzer(llm, enable_cache=False)

# Analyze a page
async with browser.page("session-1") as page:
    await page.goto("https://example.com/login")
    html = await page.content()
    
    # AI analysis
    analysis = await analyzer.analyze_page(html, page.url)
    
    # View results
    print(f"Found {len(analysis.form_fields)} fields")
    for field in analysis.form_fields:
        print(f"  - {field.purpose}: {field.selector}")
    
    print(f"\nAction sequence: {len(analysis.action_sequence)} steps")
    for action in analysis.action_sequence:
        print(f"  {action.order}. {action.action_type}: {action.description}")
```

## Data Models

### FormField

Represents an identified form field:

```python
@dataclass
class FormField:
    selector: str           # CSS/XPath selector
    field_type: str        # input type: text, email, password, etc.
    purpose: FieldPurpose  # What this field is for
    label: Optional[str]   # Field label text
    placeholder: Optional[str]
    required: bool
    confidence: float      # AI confidence (0.0-1.0)
    attributes: Dict[str, Any]
```

### FieldPurpose (Enum)

```python
class FieldPurpose(str, Enum):
    EMAIL = "email"
    PASSWORD = "password"
    USERNAME = "username"
    PHONE = "phone"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    ADDRESS = "address"
    CITY = "city"
    COUNTRY = "country"
    POSTAL_CODE = "postal_code"
    DATE_OF_BIRTH = "date_of_birth"
    PASSPORT_NUMBER = "passport_number"
    OTP = "otp"
    CAPTCHA = "captcha"
    # ... more
```

### ActionStep

Represents an action to perform:

```python
@dataclass
class ActionStep:
    action_type: ActionType  # fill, click, select, wait
    selector: str           # Target element selector
    description: str        # Human-readable description
    order: int             # Sequence number
    value_source: Optional[str]  # e.g., "credentials.username"
    wait_after: int        # Milliseconds to wait after
```

### PageAnalysis

Complete analysis result:

```python
@dataclass
class PageAnalysis:
    url: str
    form_fields: List[FormField]
    action_sequence: List[ActionStep]
    submit_button: Optional[ActionStep]
    has_captcha: bool
    has_otp: bool
    metadata: Dict[str, Any]
```

## Testing

### Test Scripts

Three test modes are available:

```bash
# Test 1: Page analyzer only (no form filling)
python scripts/test_ai_form_filler.py analyzer

# Test 2: Full AI login flow with regular browser
python scripts/test_ai_form_filler.py login

# Test 3: AI + HybridBrowser (BQL + Playwright)
python scripts/test_ai_form_filler.py hybrid
```

### Test Output

The analyzer will display:

```
================================================================================
ANALYSIS RESULTS
================================================================================
URL: https://visa.vfsglobal.com/tur/tr/fra/login
Form Fields: 2
Actions: 3
Has CAPTCHA: False
Has OTP: True

📝 IDENTIFIED FORM FIELDS:

  1. EMAIL
     Selector: input#Email
     Type: email
     Label: E-posta*
     Required: True
     Confidence: 0.95

  2. PASSWORD
     Selector: input#Password
     Type: password
     Label: Şifre*
     Required: True
     Confidence: 0.95

🔄 ACTION SEQUENCE:

  1. FILL
     Description: Fill email field
     Selector: input#Email
     Value from: credentials.username
     Wait after: 500ms

  2. FILL
     Description: Fill password field
     Selector: input#Password
     Value from: credentials.password
     Wait after: 500ms

  3. CLICK
     Description: Click submit button
     Selector: button[type='submit']

✅ SUBMIT BUTTON: button[type='submit']
================================================================================
```

## Advantages

### 🎯 Intelligent Adaptation

- **No hardcoded selectors**: AI identifies fields dynamically
- **Adapts to page changes**: If site structure changes, AI adapts
- **Works across sites**: Same code works for different websites

### 🔄 Automatic Fallback

- AI analysis fails → Falls back to manual selectors
- Best of both worlds: intelligence + reliability

### 🧠 Context-Aware

- Understands field purpose from context (labels, attributes, position)
- Creates logical action sequences
- Handles multi-step forms intelligently

### 📊 Transparent

- Logs every step for debugging
- Shows confidence scores
- Captures screenshots at each stage

## Limitations & Considerations

### Cost

- Each page analysis costs ~$0.001-0.005 (GPT-4o-mini)
- Analysis is cached per session
- Fallback to manual selectors is free

### Accuracy

- AI confidence typically 0.85-0.95 for standard forms
- Complex dynamic forms may need manual selectors
- Always test before production use

### Performance

- Analysis adds ~2-5 seconds per page
- One-time cost per session (cached)
- Parallel analysis possible for multiple pages

## Best Practices

### 1. Fresh Data on Each Login

**Always provide `session_store` for fresh data:**

```python
provider = VfsAvailabilityProvider(
    browser,
    email_service=email_service,
    llm=llm,
    enable_ai_form_filling=True,
    session_store=session_store,  # ✅ Fresh data each time
)
```

This ensures:
- ✅ Latest credentials are used
- ✅ Updated profile data
- ✅ No stale session data
- ✅ HTML is re-analyzed each time

### 2. Disable Cache for Dynamic Pages

For pages that change frequently:

```python
analyzer = PageAnalyzer(llm, enable_cache=False)  # ✅ Fresh analysis
```

### 3. Enable Fallback

Always keep manual selectors as fallback:

```python
# VfsAvailabilityProvider already implements this pattern
if self.page_analyzer and page_content:
    # Try AI first
    success = await self._ai_form_fill(page, page_content, session)
    if success:
        return
    # If AI fails, continue to manual selectors below
    logger.warning("AI failed, using manual selectors")

# Manual selector code here...
```

### 2. Log Extensively

The PageAnalyzer logs every step. Keep these logs for debugging:

```python
logger.info(f"AI identified {len(fields)} fields")
for field in fields:
    logger.info(f"  - {field.purpose}: {field.selector} (conf: {field.confidence})")
```

### 3. Test Before Production

Always test AI form filling with your specific site:

```bash
python scripts/test_ai_form_filler.py analyzer
```

Review the identified fields and action sequence before enabling in production.

### 4. Handle Edge Cases

```python
# Check for CAPTCHA
if analysis.has_captcha:
    logger.warning("Page has CAPTCHA, may need manual intervention")

# Check for OTP
if analysis.has_otp:
    await handle_otp(analysis)
```

### 5. Set Appropriate Timeouts

```python
# Give AI time to analyze
analysis = await analyzer.analyze_page(html, page.url)

# Give actions time to complete
if action.wait_after > 0:
    await asyncio.sleep(action.wait_after / 1000)
```

## Troubleshooting

### Issue: "No form fields identified"

**Cause**: AI couldn't find form elements in HTML

**Solutions**:
1. Check if page is fully loaded (wait for `networkidle`)
2. Verify HTML contains form elements
3. Check if forms are in shadow DOM (not supported yet)
4. Increase `max_html_length` in PageAnalyzer

### Issue: "Field selector not found"

**Cause**: AI generated invalid or incorrect selector

**Solutions**:
1. Check confidence score - low confidence = unreliable
2. Verify page structure hasn't changed during analysis
3. Use fallback to manual selectors
4. Review HTML to understand why selector failed

### Issue: "AI form filling too slow"

**Cause**: LLM API latency

**Solutions**:
1. Use faster model (gpt-4o-mini is already fast)
2. Cache analysis results per page type
3. Reduce HTML size sent to LLM
4. Run analysis in parallel for multiple pages

### Issue: "Incorrect fields identified"

**Cause**: Ambiguous HTML or misleading labels

**Solutions**:
1. Check field labels and attributes in HTML
2. Review AI confidence scores
3. Add more context to LLM prompts
4. Use manual selectors for problematic fields

## Architecture

### Component Diagram

```
┌──────────────────────────────────────────────────┐
│ VfsAvailabilityProvider                          │
│ - enable_ai_form_filling: bool                   │
│ - page_analyzer: PageAnalyzer                    │
│                                                  │
│ Methods:                                         │
│ + ensure_login(session)                          │
│ + _ai_form_fill(page, html, session) → bool     │
└─────────────┬────────────────────────────────────┘
              │ uses
              ▼
┌──────────────────────────────────────────────────┐
│ PageAnalyzer                                     │
│ - llm: LLMClient                                 │
│                                                  │
│ Methods:                                         │
│ + analyze_page(html, url) → PageAnalysis        │
│ + identify_form_fields(html) → List[FormField]  │
│ + identify_submit_sequence(...) → List[Action]  │
│ + get_value_from_session(path, data) → str      │
└─────────────┬────────────────────────────────────┘
              │ uses
              ▼
┌──────────────────────────────────────────────────┐
│ LLMClient (OpenAI)                               │
│ - api_key: str                                   │
│ - model: str                                     │
│                                                  │
│ Methods:                                         │
│ + generate(system, user, temp) → str            │
└──────────────────────────────────────────────────┘
```

## See Also

- [Hybrid Browser Documentation](./hybrid-browser.md) - BQL + Playwright setup
- [Main README](../README.md) - General project overview
- [VFS Flow Implementation](../src/agentbot/site/vfs_fra_flow.py) - Example usage

