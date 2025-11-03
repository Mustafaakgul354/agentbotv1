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


LOGIN_URL = "https://visa.vfsglobal.com/tur/en/fra/login"
DASHBOARD_URL = "https://visa.vfsglobal.com/tur/en/fra/dashboard"
APPT_DETAIL_URL = "https://visa.vfsglobal.com/tur/en/fra/application-detail"
BOOK_URL = "https://visa.vfsglobal.com/tur/en/fra/book-appointment"


logger = get_logger("VFSFlow")


@dataclass
class VfsSelectors:
    email: str = 'input[type="email"]'
    password: str = 'input[type="password"]:below(:text("Password"))'
    sign_in: str = 'button:has-text("Sign In")'
    otp: str = 'input[autocomplete="one-time-code"], input[type="password"]'
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
        credentials = session.credentials
        async with self.browser.page(session.session_id) as page:
            await page.goto(LOGIN_URL)
            await await_turnstile_if_present(page, timeout=8000)
            await page.fill(VfsSelectors.email, credentials.get("username", ""))
            await page.fill(VfsSelectors.password, credentials.get("password", ""))
            await page.click(VfsSelectors.sign_in)
            await await_turnstile_if_present(page, timeout=12000)
            await save_screenshot(page, session.session_id, "after-login-submit")

            # OTP step
            try:
                await page.wait_for_selector(VfsSelectors.otp, timeout=15000)
                verification_code = await self.email_service.fetch_latest_code(
                    timeout=90,
                    subject_filters=["VFS", "one time password", "OTP"],
                    unseen_only=True,
                    lookback=30,
                )
                if verification_code:
                    await page.fill(VfsSelectors.otp, verification_code)
                    await page.click(VfsSelectors.sign_in)
            except Exception:
                pass  # already logged in or bypassed

            await page.wait_for_url("**/dashboard", timeout=30000)

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
                    response_data = await response.json()
                    # Attempt common shapes
                    slot_items = response_data.get("slots") or response_data.get("data") or []
                    for slot_item in slot_items:
                        timestamp_str = slot_item.get("start") or slot_item.get("start_time") or slot_item.get("datetime")
                        if not timestamp_str:
                            continue
                        try:
                            slot_datetime = dt.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        except Exception:
                            continue
                        slots.append(
                            AppointmentAvailability(
                                session_id=session.session_id,
                                slot_id=str(slot_item.get("id") or slot_item.get("slot_id") or slot_datetime.isoformat()),
                                slot_time=slot_datetime,
                                location=session.preferences.get("centre"),
                                extra=slot_item,
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
                calendar_cells = await page.query_selector_all(VfsSelectors.calendar_cell)
                if not calendar_cells:
                    return slots
                await calendar_cells[0].click()
                await page.wait_for_selector(VfsSelectors.time_slot, timeout=5000)
                await save_screenshot(page, session.session_id, "slots-visible")
                time_slot_buttons = await page.query_selector_all(VfsSelectors.time_slot)
                for index, button in enumerate(time_slot_buttons[:3]):
                    current_time = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                    slots.append(
                        AppointmentAvailability(
                            session_id=session.session_id,
                            slot_id=f"dom-{index}",
                            slot_time=current_time,
                            location=session.preferences.get("centre", "VFS Centre"),
                            extra={"dom_index": index},
                        )
                    )
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
            user_preferences = session.preferences
            try:
                if centre := user_preferences.get("centre"):
                    await page.click(VfsSelectors.app_centre)
                    await page.get_by_text(str(centre), exact=False).click()
                if category := user_preferences.get("category"):
                    await page.click(VfsSelectors.category)
                    await page.get_by_text(str(category), exact=False).click()
                if subcategory := user_preferences.get("sub_category"):
                    await page.click(VfsSelectors.subcategory)
                    await page.get_by_text(str(subcategory), exact=False).click()
                await page.click(VfsSelectors.save_next)
            except Exception:
                pass

            # Step 2: fill applicant details (optional, if required)
            try:
                await page.goto("https://visa.vfsglobal.com/tur/en/fra/your-details")
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
                time_slot_buttons = await page.query_selector_all(VfsSelectors.time_slot)
                if not time_slot_buttons:
                    return AppointmentBookingResult(
                        session_id=request.session_id,
                        success=False,
                        slot=request.slot,
                        message="No slots visible at booking time",
                    )
                await time_slot_buttons[0].click()
                await page.click(VfsSelectors.confirm)
                await asyncio.sleep(1)
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=True,
                    slot=request.slot,
                    confirmation_number=None,
                )
            except Exception as error:
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=False,
                    slot=request.slot,
                    message=str(error),
                )


