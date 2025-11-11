"""VFS Global TR/EN/FRA site flow (Playwright-based).

This module encapsulates login (email+password -> OTP), dashboard navigation,
availability probing, and booking actions using Playwright. It implements the
AvailabilityProvider and BookingProvider protocols consumed by our agents.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from agentbot.agents.booking import BookingProvider
from agentbot.agents.monitor import AvailabilityProvider
from agentbot.browser.play import BrowserFactory
from agentbot.browser.humanlike import humanlike_click
from agentbot.core.models import (
    AppointmentAvailability,
    AppointmentBookingRequest,
    AppointmentBookingResult,
)
from agentbot.data.session_store import SessionRecord, SessionStore
from agentbot.services.email import EmailInboxService
from agentbot.services.form_filler import FormFiller
from agentbot.services.llm import LLMClient
from agentbot.services.page_analyzer import PageAnalyzer, ActionType, FieldPurpose
from agentbot.utils.logging import get_logger
from .turnstile import await_turnstile_if_present
from agentbot.utils.artifacts import save_screenshot
from agentbot.app.models import AppState


LOGIN_URL = "https://visa.vfsglobal.com/tur/tr/fra/login"
DASHBOARD_URL = "https://visa.vfsglobal.com/tur/tr/fra/dashboard"
APPT_DETAIL_URL = "https://visa.vfsglobal.com/tur/tr/fra/application-detail"
BOOK_URL = "https://visa.vfsglobal.com/tur/tr/fra/book-appointment"


logger = get_logger("VFSFlow")


@dataclass
class VfsSelectors:
    """VFS site selectors using XPath and CSS.
    
    ⚠️  UYARI: XPath'ler hassas olabilir ve sayfa güncellendiğinde kırılabilir.
    Sayfa yapısı değiştiğinde bu selector'ları test edin ve güncelleyin.
    
    WARNING: XPaths may be sensitive and can break if the page structure is updated.
    Test and update these selectors when the page structure changes.
    """
    # Login layout (XPath selectors derived from latest Turkish locale markup)
    login_root: str = "xpath=//app-root[@class='d-flex flex-column min-vh-100']"
    login_container: str = "xpath=//app-login[contains(@class, 'container py-15 py-md-30')]"
    login_card: str = "xpath=//mat-card[contains(@class, 'mat-mdc-card mdc-card px-md-40 py-md-40')]"
    login_form: str = "xpath=//form[@novalidate and @autocomplete='new-form']"
    login_title: str = "xpath=//h1[contains(text(), 'Oturum Aç')]"
    login_email_wrapper: str = "xpath=//mat-form-field[.//mat-label[text()='E-posta*']]"
    login_password_wrapper: str = "xpath=//mat-form-field[.//mat-label[text()='Şifre*']]"
    cloudflare_success: str = "xpath=//div[(contains(@class, 'cloudflare-success') or contains(text(), 'Başarılı!'))]"

    # Login inputs and actions (with fallback selectors)
    email: str = "xpath=//input[@id='Email' and @type='email']"
    email_fallback: str = "input#Email, input[type='email'][id='Email'], input[type='email']"
    password: str = "xpath=//input[@id='Password' and @type='password']"
    password_fallback: str = "input#Password, input[type='password'][id='Password'], input[type='password']"
    sign_in: str = "xpath=//button[normalize-space(text())='Oturum Aç']"
    sign_in_fallback: str = 'button:has-text("Oturum Aç"), button:has-text("Sign In")'
    otp: str = 'input[autocomplete="one-time-code"], input[type="password"]'

    # Misc navigation (CSS maintained where XPath not provided)
    start_booking: str = 'button:has-text("Start New Booking"), a:has-text("Start New Booking")'
    app_centre: str = 'label:has-text("Choose your Application Centre") ~ *'
    category: str = 'label:has-text("Choose your appointment category") ~ *'
    subcategory: str = 'label:has-text("Choose your sub-category") ~ *'
    save_next: str = 'button:has-text("Save"), button:has-text("Next"), button:has-text("Continue")'
    calendar_cell: str = '[role="gridcell"], .mat-calendar-body-cell:not(.mat-calendar-body-disabled)'
    time_slot: str = '.time-slots button, .slot button, button:has-text("AM"), button:has-text("PM")'
    confirm: str = 'button:has-text("Book"), button:has-text("Confirm"), button:has-text("Proceed")'


class VfsAvailabilityProvider(AvailabilityProvider):
    def __init__(
        self,
        browser: BrowserFactory,
        *,
        email_service: EmailInboxService,
        llm: Optional[LLMClient] = None,
        enable_ai_form_filling: bool = False,
        session_store: Optional["SessionStore"] = None,
        config: Optional[dict] = None,
    ) -> None:
        self.browser = browser
        self.email_service = email_service
        self.llm = llm
        self.enable_ai_form_filling = enable_ai_form_filling
        self.page_analyzer = PageAnalyzer(llm, enable_cache=False) if llm and enable_ai_form_filling else None
        self.session_store = session_store
        self.config = config or {}
        self.mouse_config = self.config.get("humanlike_mouse", {})

    async def _click(self, page: Page, target: LocatorLike):
        """Helper to standardize clicks with configured behavior."""
        await humanlike_click(page, target, config=self.mouse_config)

    async def _smart_fill_with_locator(
        self,
        page: Page,
        *,
        keywords: Sequence[str],
        value: str,
        debug_name: str,
        input_selector: str = "input",
        timeout: int = 4000,
    ) -> bool:
        """Attempt to fill a field by progressively smarter locator heuristics."""
        if not value:
            return False

        locator = await self._smart_locate_field(
            page,
            keywords=keywords,
            debug_name=debug_name,
            input_selector=input_selector,
            timeout=timeout,
        )
        if locator:
            await locator.fill(value)
            logger.info("%s filled via Locator API (%s)", debug_name, locator)
            return True
        return False

    async def _smart_locate_field(
        self,
        page: Page,
        *,
        keywords: Sequence[str],
        debug_name: str,
        input_selector: str = "input",
        timeout: int = 4000,
    ) -> Optional[Locator]:
        patterns = [re.compile(keyword, re.IGNORECASE) for keyword in keywords if keyword]
        if not patterns:
            return None

        candidate_locators: List[tuple[str, Locator]] = []
        for pattern in patterns:
            candidate_locators.extend(
                [
                    (f"label:{pattern.pattern}", page.get_by_label(pattern)),
                    (f"placeholder:{pattern.pattern}", page.get_by_placeholder(pattern)),
                    (f"role:{pattern.pattern}", page.get_by_role("textbox", name=pattern)),
                ]
            )

            mat_form = page.locator("mat-form-field").filter(has_text=pattern)
            candidate_locators.append((f"mat-form-field:{pattern.pattern}", mat_form.locator(input_selector)))

            keyword = pattern.pattern.replace("'", "\\'")
            attr_selector = (
                f"{input_selector}[id*=\"{keyword}\" i], "
                f"{input_selector}[name*=\"{keyword}\" i], "
                f"{input_selector}[formcontrolname*=\"{keyword}\" i]"
            )
            candidate_locators.append((f"attribute:{pattern.pattern}", page.locator(attr_selector)))

        for source, candidate in candidate_locators:
            try:
                handle = candidate.first
                await handle.wait_for(state="visible", timeout=timeout)
                logger.debug("Located %s via %s", debug_name, source)
                return handle
            except PlaywrightTimeoutError:
                logger.debug("Locator %s for %s timed out", source, debug_name)
            except Exception as exc:
                logger.debug("Locator %s for %s failed: %s", source, debug_name, exc)
        return None

    async def ensure_login(self, session: SessionRecord) -> None:
        # 🔄 Her seferinde fresh session data çek (eğer store varsa)
        if self.session_store:
            logger.info("🔄 Fetching fresh session data from store...")
            fresh_session = await self.session_store.get(session.session_id)
            if fresh_session:
                session = fresh_session
                logger.info("✅ Using fresh session data")
                logger.info(f"   Session ID: {session.session_id}")
                logger.info(f"   User: {session.email}")
            else:
                logger.warning("⚠️ Could not fetch fresh session, using provided")
        
        creds = session.credentials or {}
        username = creds.get("username", "")
        password = creds.get("password", "")
        async with self.browser.page(session.session_id) as page:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            
            # Önce zaten login olup olmadığını kontrol et
            await asyncio.sleep(2)  # Biraz daha uzun bekleme, redirect ve JavaScript için
            current_url = page.url
            logger.info(f"Current URL after navigation: {current_url}")
            
            if "/dashboard" in current_url:
                logger.info("Already logged in, skipping login flow")
                return
            
            # İlk screenshot - sayfa yüklendikten hemen sonra
            await save_screenshot(page, session.session_id, "01-after-navigation")
            
            # Cloudflare challenge detection and bypass with BQL stealth
            # Eğer Cloudflare challenge tetiklenirse, BQL stealth ile aşın
            # await_turnstile_if_present automatically detects and handles challenges
            logger.info("Checking for Cloudflare challenge...")
            await await_turnstile_if_present(page, timeout=15000)
            await save_screenshot(page, session.session_id, "02-after-turnstile")
            
            # Handle Cookie Consent Banner
            try:
                logger.info("Checking for cookie consent banner...")
                cookie_accept_button = page.locator("#onetrust-accept-btn-handler")
                await cookie_accept_button.wait_for(state="visible", timeout=15000)
                await self._click(page, cookie_accept_button)
                logger.info("✓ Accepted all cookies.")
                await page.wait_for_load_state("networkidle", timeout=10000) # Wait for page to settle
            except Exception as e:
                logger.info(f"Cookie consent banner not found or failed to click: {e}")

            # Sayfanın tam yüklenmesini bekle
            logger.info("Waiting for page to fully load...")
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
                logger.info("Page reached networkidle state")
            except Exception as e:
                logger.warning(f"Network idle timeout: {e}, continuing anyway")
            
            await save_screenshot(page, session.session_id, "03-after-networkidle")
            
            # Sayfa içeriğini debug için kaydet
            page_content = ""
            try:
                page_content = await page.content()
                from pathlib import Path
                html_path = Path("artifacts") / session.session_id / "page-content.html"
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(page_content, encoding="utf-8")
                logger.info(f"Page HTML saved to: {html_path}")
            except Exception as e:
                logger.warning(f"Failed to save page HTML: {e}")
            
            # Try AI-powered form filling first
            if self.page_analyzer and page_content:
                logger.info("🤖 Attempting AI-powered form filling...")
                try:
                    ai_success = await self._ai_form_fill(page, page_content, session)
                    if ai_success:
                        logger.info("✅ AI form filling successful!")
                        # Wait for navigation to dashboard
                        await page.wait_for_url("**/dashboard", timeout=30000)
                        logger.info("Successfully logged in via AI and reached dashboard")
                        return
                    else:
                        logger.warning("⚠️ AI form filling failed, falling back to manual selectors")
                except Exception as e:
                    logger.warning(f"⚠️ AI form filling error: {e}, falling back to manual selectors")
            
            # Fallback: Manual selector-based form filling
            logger.info("Using manual selector-based form filling...")
            
            # Sayfadaki tüm input elementlerini listele (debug)
            try:
                all_inputs = await page.query_selector_all("input")
                logger.info(f"Found {len(all_inputs)} input elements on page")
                for idx, inp in enumerate(all_inputs[:10]):  # İlk 10 input
                    inp_type = await inp.get_attribute("type")
                    inp_id = await inp.get_attribute("id")
                    inp_name = await inp.get_attribute("name")
                    inp_class = await inp.get_attribute("class")
                    logger.info(f"  Input {idx}: type={inp_type}, id={inp_id}, name={inp_name}, class={inp_class}")
            except Exception as e:
                logger.warning(f"Failed to enumerate inputs: {e}")
            
            # Login form elementlerini daha esnek şekilde bekle
            logger.info("Looking for login form elements...")
            try:
                await page.wait_for_selector(VfsSelectors.login_card, timeout=30000)
                logger.info("✓ Login card found")
            except Exception as e:
                logger.warning(f"✗ Login card not found: {e}")
                try:
                    # Fallback: email input'u bekle (daha uzun timeout)
                    logger.info("Trying fallback: waiting for email input...")
                    await page.wait_for_selector(VfsSelectors.email, timeout=30000, state="visible")
                    logger.info("✓ Email input found via fallback")
                except Exception as e2:
                    # Son fallback: herhangi bir email input bekle
                    logger.error(f"✗ Email input not found with primary selector: {e2}")
                    await save_screenshot(page, session.session_id, "04-login-error")
                    logger.error(f"Current URL: {page.url}")
                    
                    # Tüm olası email input selector'larını dene
                    logger.info("Trying all possible email input selectors...")
                    possible_selectors = [
                        "input[type='email']",
                        "input[name='email']",
                        "input[id*='mail' i]",
                        "input[placeholder*='mail' i]",
                        "input[autocomplete='email']",
                    ]
                    
                    found = False
                    for selector in possible_selectors:
                        try:
                            logger.info(f"  Trying selector: {selector}")
                            await page.wait_for_selector(selector, timeout=5000, state="visible")
                            logger.info(f"  ✓ Found with selector: {selector}")
                            found = True
                            break
                        except Exception:
                            logger.info(f"  ✗ Not found with: {selector}")
                    
                    if not found:
                        logger.error("No email input found with any selector!")
                        logger.error("This might indicate:")
                        logger.error("  1. Page is still loading")
                        logger.error("  2. Cloudflare/bot protection is blocking")
                        logger.error("  3. Site structure has changed")
                        logger.error("  4. Already logged in but redirect failed")
                        raise Exception("No email input element found on login page")
            
            try:
                await page.wait_for_selector(VfsSelectors.cloudflare_success, timeout=5000)
                logger.debug("Cloudflare success banner detected")
            except Exception:
                pass  # Cloudflare success banner not always shown
            
            # Email input'un editable olmasını bekle
            email_filled = False
            try:
                email_locator = page.locator(VfsSelectors.email).first
                await email_locator.wait_for(state="visible", timeout=10000)
                await email_locator.fill(username)
                await asyncio.sleep(0.3) # Add a small delay
                logger.debug("Email filled successfully")
                email_filled = True
            except Exception as e:
                logger.warning(f"Failed to fill email with primary method: {e}")

            if not email_filled:
                try:
                    email_filled = await self._smart_fill_with_locator(
                        page,
                        keywords=("email", "e-posta", "mail"),
                        value=username,
                        debug_name="email",
                    )
                    if email_filled:
                        logger.debug("Email filled via Locator API smart detection")
                except Exception as smart_exc:
                    logger.debug(f"Smart locator email fill failed: {smart_exc}")

            if not email_filled:
                try:
                    await page.fill(VfsSelectors.email_fallback, username)
                    logger.debug("Email filled via fallback selector")
                    email_filled = True
                except Exception as e2:
                    logger.error(f"Failed to fill email with fallback: {e2}")
                    raise
            
            # Password input'u doldur
            password_filled = False
            try:
                await page.fill(VfsSelectors.password, password)
                await asyncio.sleep(0.4) # Add a small delay
                logger.debug("Password filled successfully")
                password_filled = True
            except Exception as e:
                logger.warning(f"Failed to fill password with primary method: {e}")

            if not password_filled:
                try:
                    password_filled = await self._smart_fill_with_locator(
                        page,
                        keywords=("password", "şifre"),
                        value=password,
                        debug_name="password",
                        input_selector='input[type="password"]',
                    )
                    if password_filled:
                        logger.debug("Password filled via Locator API smart detection")
                except Exception as smart_exc:
                    logger.debug(f"Smart locator password fill failed: {smart_exc}")

            if not password_filled:
                try:
                    await page.fill(VfsSelectors.password_fallback, password)
                    logger.debug("Password filled via fallback selector")
                    password_filled = True
                except Exception as e2:
                    logger.error(f"Failed to fill password with fallback: {e2}")
                    raise
            
            await save_screenshot(page, session.session_id, "before-login-submit")
            
            try:
                await self._click(page, VfsSelectors.sign_in)
            except Exception:
                await self._click(page, VfsSelectors.sign_in_fallback)
            
            # Cloudflare challenge may appear after login submit - bypass with BQL stealth
            await await_turnstile_if_present(page, timeout=15000)
            await save_screenshot(page, session.session_id, "after-login-submit")

            # OTP step
            try:
                await page.wait_for_selector(VfsSelectors.otp, timeout=15000)
                logger.info("OTP input detected, waiting for email code")
                code = await self.email_service.fetch_latest_code(
                    timeout=90,
                    subject_filters=["VFS", "one time password", "OTP"],
                    unseen_only=True,
                    lookback=30,
                )
                if code:
                    logger.info(f"OTP code received: {code[:2]}***")
                    await page.fill(VfsSelectors.otp, code)
                    await asyncio.sleep(0.5)  # Add a small delay
                    try:
                        await self._click(page, VfsSelectors.sign_in)
                    except Exception:
                        await self._click(page, VfsSelectors.sign_in_fallback)
                    await await_turnstile_if_present(page, timeout=15000)
                else:
                    logger.warning("No OTP code received from email")
            except Exception as e:
                logger.debug(f"OTP step skipped or failed: {e}")
                pass  # already logged in or bypassed

            await page.wait_for_url("**/dashboard", timeout=30000)
            logger.info("Successfully logged in and reached dashboard")

    async def check(self, session: SessionRecord) -> Iterable[AppointmentAvailability]:
        slots: List[AppointmentAvailability] = []
        async with self.browser.page(session.session_id) as page:
            await page.goto(BOOK_URL)

            # Try to capture JSON responses that include slots
            try:
                response = await page.wait_for_response(
                    lambda r: ("calendar" in r.url or "slot" in r.url) and r.status == 200,
                    timeout=5000,
                )
                try:
                    data = await response.json()
                    # Attempt common shapes
                    items = data.get("slots") or data.get("data") or []
                    for item in items:
                        ts = item.get("start") or item.get("start_time") or item.get("datetime")
                        if not ts:
                            continue
                        try:
                            when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except Exception:
                            continue
                        slots.append(
                            AppointmentAvailability(
                                session_id=session.session_id,
                                slot_id=str(item.get("id") or item.get("slot_id") or when.isoformat()),
                                slot_time=when,
                                location=session.preferences.get("centre"),
                                extra=item,
                            )
                        )
                    if slots:
                        return slots
                except Exception:
                    pass
            except Exception:
                pass

            # Optional LLM-assisted classification when no structured data is found
            if not slots and self.llm:
                try:
                    body_text = await page.inner_text("body")
                    snippet = body_text[:4000]
                    answer = await self.llm.generate(
                        system="You classify appointment pages.",
                        user=(
                            "Answer strictly 'yes' or 'no'. Does this text explicitly say no appointments are available right now?\n\n"
                            + snippet
                        ),
                        temperature=0.0,
                    )
                    if answer.lower().strip().startswith("yes"):
                        return []
                except Exception:
                    pass

            # Fallback: parse DOM
            try:
                await page.wait_for_selector(VfsSelectors.calendar_cell, timeout=10000)
                # Try first enabled date cell
                cells = await page.query_selector_all(VfsSelectors.calendar_cell)
                if not cells:
                    return slots
                await self._click(page, cells[0])
                await page.wait_for_selector(VfsSelectors.time_slot, timeout=5000)
                await save_screenshot(page, session.session_id, "slots-visible")
                t_buttons = await page.query_selector_all(VfsSelectors.time_slot)
                for idx, btn in enumerate(t_buttons[:3]):
                    ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                    slots.append(
                        AppointmentAvailability(
                            session_id=session.session_id,
                            slot_id=f"dom-{idx}",
                            slot_time=ts,
                            location=session.preferences.get("centre", "VFS Centre"),
                            extra={"dom_index": idx},
                        )
                    )
            except Exception:
                logger.debug("No available slots detected via DOM")
        return slots

    async def _ai_form_fill(self, page, html_content: str, session: SessionRecord) -> bool:
        """Fill form using AI page analyzer.
        
        Args:
            page: Playwright page object
            html_content: HTML content of the page
            session: Session record with credentials
            
        Returns:
            True if successful, False otherwise
        """
        if not self.page_analyzer:
            return False
        
        try:
            # 🔄 HER SEFERINDE FRESH ANALIZ
            logger.info("🔄 Starting fresh page analysis...")
            logger.info(f"   Session ID: {session.session_id}")
            logger.info(f"   User: {session.email}")
            logger.info(f"   Page URL: {page.url}")
            
            # Analyze the page (her seferinde yeniden)
            logger.info("📊 Analyzing page structure with AI...")
            analysis = await self.page_analyzer.analyze_page(html_content, page.url)
            
            if not analysis.form_fields:
                logger.warning("⚠️ No form fields identified by AI")
                return False
            
            logger.info(f"✅ AI identified {len(analysis.form_fields)} form fields")
            for field in analysis.form_fields:
                logger.info(f"  - {field.purpose.value}: {field.selector} (confidence: {field.confidence:.2f})")
            
            # 🔄 Session datayı her seferinde fresh olarak hazırla
            logger.info("📖 Reading session data...")
            session_data = {
                "credentials": {
                    "username": session.credentials.get("username"),
                    "password": session.credentials.get("password"),
                },
                "profile": dict(session.profile),  # Fresh copy
                "preferences": dict(session.preferences),  # Fresh copy
            }
            
            logger.info(f"   Username: {session_data['credentials']['username'][:3] if session_data['credentials'].get('username') else 'N/A'}***")
            logger.info(f"   Profile fields: {len(session_data['profile'])}")
            logger.info(f"   Preferences: {len(session_data['preferences'])}")
            
            # Execute action sequence
            if analysis.action_sequence:
                logger.info(f"🎬 Executing {len(analysis.action_sequence)} actions in sequence...")
                for action in analysis.action_sequence:
                    try:
                        logger.info(f"▶️  Action {action.order}: {action.description}")
                        
                        if action.action_type == ActionType.FILL:
                            # 🔄 Her action için value'yu fresh oku
                            value = self.page_analyzer.get_value_from_session(
                                action.value_source or "", 
                                session_data
                            )
                            if value:
                                logger.info(f"   📝 Value source: {action.value_source}")
                                logger.info(f"   📝 Value length: {len(str(value))} chars")
                                await page.fill(action.selector, value)
                                logger.info(f"   ✅ Filled {action.selector}")
                            else:
                                logger.warning(f"   ⚠️  No value for {action.value_source}")
                        
                        elif action.action_type == ActionType.CLICK:
                            await self._click(page, action.selector)
                            logger.info(f"   ✅ Clicked {action.selector}")
                        
                        elif action.action_type == ActionType.SELECT:
                            if action.value_source:
                                value = self.page_analyzer.get_value_from_session(
                                    action.value_source, 
                                    session_data
                                )
                                if value:
                                    await page.select_option(action.selector, value)
                                    logger.info(f"   ✅ Selected {value} in {action.selector}")
                        
                        elif action.action_type == ActionType.WAIT:
                            wait_time = action.wait_after or 1000
                            await asyncio.sleep(wait_time / 1000)
                            logger.info(f"   ⏱️  Waited {wait_time}ms")
                        
                        # Wait after action if specified
                        if action.wait_after > 0:
                            await asyncio.sleep(action.wait_after / 1000)
                    
                    except Exception as e:
                        logger.warning(f"   ❌ Action failed: {e}")
                        # Don't fail completely, continue with next action
                        continue
            
            # Take screenshot after form filling
            await save_screenshot(page, session.session_id, "04-ai-form-filled")
            
            # Check if we need to handle OTP
            if analysis.has_otp:
                logger.info("Page requires OTP, waiting for email code...")
                try:
                    # Wait for OTP field to appear
                    otp_field = next(
                        (f for f in analysis.form_fields if f.purpose == FieldPurpose.OTP),
                        None
                    )
                    if otp_field:
                        await page.wait_for_selector(otp_field.selector, timeout=15000)
                        code = await self.email_service.fetch_latest_code(
                            timeout=90,
                            subject_filters=["VFS", "one time password", "OTP"],
                            unseen_only=True,
                            lookback=30,
                        )
                        if code:
                            logger.info(f"OTP code received: {code[:2]}***")
                            await page.fill(otp_field.selector, code)
                            # Click submit again if needed
                            if analysis.submit_button:
                                await self._click(page, analysis.submit_button.selector)
                except Exception as e:
                    logger.warning(f"OTP handling failed: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"AI form filling failed: {e}", exc_info=True)
            return False


class VfsBookingProvider(BookingProvider):
    def __init__(self, browser: BrowserFactory, *, email_service: EmailInboxService, form_filler: Optional[FormFiller] = None, config: Optional[dict] = None) -> None:
        self.browser = browser
        self.email_service = email_service
        self.form_filler = form_filler
        self.config = config or {}
        self.mouse_config = self.config.get("humanlike_mouse", {})

    async def _click(self, page: Page, target: LocatorLike):
        """Helper to standardize clicks with configured behavior."""
        await humanlike_click(page, target, config=self.mouse_config)

    async def book(self, request: AppointmentBookingRequest, session: SessionRecord) -> AppointmentBookingResult:
        async with self.browser.page(session.session_id) as page:
            # Assume already logged in; navigate to appointment flow
            await page.goto(APPT_DETAIL_URL)

            # Step 1: selections from preferences
            prefs = session.preferences
            try:
                if centre := prefs.get("centre"):
                    await self._click(page, VfsSelectors.app_centre)
                    await self._click(page, page.get_by_text(str(centre), exact=False))
                if category := prefs.get("category"):
                    await self._click(page, VfsSelectors.category)
                    await self._click(page, page.get_by_text(str(category), exact=False))
                if sub := prefs.get("sub_category"):
                    await self._click(page, VfsSelectors.subcategory)
                    await self._click(page, page.get_by_text(str(sub), exact=False))
                await self._click(page, VfsSelectors.save_next)
            except Exception:
                pass

            # Step 2: fill applicant details (optional, if required)
            try:
                await page.goto("https://visa.vfsglobal.com/tur/tr/fra/your-details")
                if self.form_filler:
                    await self.form_filler.populate(page, session.profile)
                # Optional passport upload if provided
                passport_path = session.profile.get("passport_image")
                if passport_path:
                    try:
                        await page.set_input_files("input[type='file']", passport_path)
                    except Exception:
                        pass
                await self._click(page, VfsSelectors.save_next)
            except Exception:
                pass

            # Step 3: book appointment page
            await page.goto(BOOK_URL)
            try:
                await page.wait_for_selector(VfsSelectors.time_slot, timeout=10000)
                buttons = await page.query_selector_all(VfsSelectors.time_slot)
                if not buttons:
                    return AppointmentBookingResult(
                        session_id=request.session_id,
                        success=False,
                        slot=request.slot,
                        message="No slots visible at booking time",
                    )
                await self._click(page, buttons[0])
                await self._click(page, VfsSelectors.confirm)
                await asyncio.sleep(1)
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=True,
                    slot=request.slot,
                    confirmation_number=None,
                )
            except Exception as exc:
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=False,
                    slot=request.slot,
                    message=str(exc),
                )
