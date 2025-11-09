"""VFS Global TR/EN/FRA site flow (Playwright-based).

This module encapsulates login (email+password -> OTP), dashboard navigation,
availability probing, and booking actions using Playwright. It implements the
AvailabilityProvider and BookingProvider protocols consumed by our agents.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List, Optional

from agentbot.agents.booking import BookingProvider
from agentbot.agents.monitor import AvailabilityProvider
from agentbot.browser.play import BrowserFactory
from agentbot.core.models import (
    AppointmentAvailability,
    AppointmentBookingRequest,
    AppointmentBookingResult,
)
from agentbot.data.session_store import SessionRecord
from agentbot.services.email import EmailInboxService
from agentbot.services.form_filler import FormFiller
from agentbot.services.llm import LLMClient
from agentbot.utils.logging import get_logger
from .turnstile import await_turnstile_if_present
from agentbot.utils.artifacts import save_screenshot


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

    # Login inputs and actions
    email: str = "xpath=//input[@id='Email' and @type='email']"
    password: str = "xpath=//input[@id='Password' and @type='password']"
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
    def __init__(self, browser: BrowserFactory, *, email_service: EmailInboxService, llm: Optional[LLMClient] = None) -> None:
        self.browser = browser
        self.email_service = email_service
        self.llm = llm

    async def ensure_login(self, session: SessionRecord) -> None:
        creds = session.credentials
        async with self.browser.page(session.session_id) as page:
            await page.goto(LOGIN_URL)
            
            # Cloudflare challenge detection and bypass with BQL stealth
            # Eğer Cloudflare challenge tetiklenirse, BQL stealth ile aşın
            # await_turnstile_if_present automatically detects and handles challenges
            await await_turnstile_if_present(page, timeout=8000)
            
            try:
                await page.wait_for_selector(VfsSelectors.login_card, timeout=20000)
            except Exception:
                await page.wait_for_selector(VfsSelectors.email, timeout=20000)
            try:
                await page.wait_for_selector(VfsSelectors.cloudflare_success, timeout=5000)
            except Exception:
                pass  # Cloudflare success banner not always shown
            await page.fill(VfsSelectors.email, creds.get("username", ""))
            await page.fill(VfsSelectors.password, creds.get("password", ""))
            try:
                await page.click(VfsSelectors.sign_in)
            except Exception:
                await page.click(VfsSelectors.sign_in_fallback)
            
            # Cloudflare challenge may appear after login submit - bypass with BQL stealth
            await await_turnstile_if_present(page, timeout=12000)
            await save_screenshot(page, session.session_id, "after-login-submit")

            # OTP step
            try:
                await page.wait_for_selector(VfsSelectors.otp, timeout=15000)
                code = await self.email_service.fetch_latest_code(
                    timeout=90,
                    subject_filters=["VFS", "one time password", "OTP"],
                    unseen_only=True,
                    lookback=30,
                )
                if code:
                    await page.fill(VfsSelectors.otp, code)
                    try:
                        await page.click(VfsSelectors.sign_in)
                    except Exception:
                        await page.click(VfsSelectors.sign_in_fallback)
            except Exception:
                pass  # already logged in or bypassed

            await page.wait_for_url("**/dashboard", timeout=30000)

    async def check(self, session: SessionRecord) -> Iterable[AppointmentAvailability]:
        slots: List[AppointmentAvailability] = []
        async with self.browser.page(session.session_id) as page:
            await page.goto(BOOK_URL)

            # PRIMARY METHOD: LLM-based analysis (if available)
            if self.llm:
                logger.info("Using LLM as primary method for slot detection")
                try:
                    body_text = await page.inner_text("body")
                    snippet = body_text[:8000]  # Increased for better context
                    answer = await self.llm.generate(
                        system=(
                            "You are an appointment availability analyzer. "
                            "Analyze the page text and determine if appointment slots are available. "
                            "If no appointments are available, respond with 'NO_SLOTS'. "
                            "If appointments might be available (you see calendar, time slots, or booking interface), respond with 'SLOTS_AVAILABLE'. "
                            "Be decisive and clear."
                        ),
                        user=(
                            "Does this page show available appointment slots or a booking calendar?\n\n"
                            f"Page content:\n{snippet}"
                        ),
                        temperature=0.0,
                    )
                    logger.info(f"LLM response: {answer}")
                    
                    # If LLM indicates no slots, return empty immediately
                    if "NO_SLOTS" in answer.upper() or answer.lower().strip().startswith("no"):
                        logger.info("LLM determined: No slots available")
                        return []
                    
                    # If LLM indicates slots might be available, continue with DOM parsing
                    logger.info("LLM determined: Slots might be available, proceeding with DOM analysis")
                except Exception as exc:
                    logger.warning(f"LLM analysis failed: {exc}, falling back to traditional methods")

            # FALLBACK 1: Try to capture JSON responses that include slots
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
                        logger.info(f"Found {len(slots)} slots via JSON API")
                        return slots
                except Exception:
                    pass
            except Exception:
                pass

            # FALLBACK 2: parse DOM
            try:
                await page.wait_for_selector(VfsSelectors.calendar_cell, timeout=10000)
                # Try first enabled date cell
                cells = await page.query_selector_all(VfsSelectors.calendar_cell)
                if not cells:
                    return slots
                await cells[0].click()
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
                logger.info(f"Found {len(slots)} slots via DOM parsing")
            except Exception:
                logger.debug("No available slots detected via DOM")
        return slots


class VfsBookingProvider(BookingProvider):
    def __init__(self, browser: BrowserFactory, *, email_service: EmailInboxService, form_filler: Optional[FormFiller] = None) -> None:
        self.browser = browser
        self.email_service = email_service
        self.form_filler = form_filler

    async def book(self, request: AppointmentBookingRequest, session: SessionRecord) -> AppointmentBookingResult:
        async with self.browser.page(session.session_id) as page:
            # Assume already logged in; navigate to appointment flow
            await page.goto(APPT_DETAIL_URL)

            # Step 1: selections from preferences
            prefs = session.preferences
            try:
                if centre := prefs.get("centre"):
                    await page.click(VfsSelectors.app_centre)
                    await page.get_by_text(str(centre), exact=False).click()
                if category := prefs.get("category"):
                    await page.click(VfsSelectors.category)
                    await page.get_by_text(str(category), exact=False).click()
                if sub := prefs.get("sub_category"):
                    await page.click(VfsSelectors.subcategory)
                    await page.get_by_text(str(sub), exact=False).click()
                await page.click(VfsSelectors.save_next)
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
                await page.click(VfsSelectors.save_next)
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
                await buttons[0].click()
                await page.click(VfsSelectors.confirm)
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
