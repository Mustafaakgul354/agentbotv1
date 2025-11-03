"""Example site provider demonstrating how to integrate with the target website.

This module keeps the example HTTP-based provider for tests. The real VFS
Playwright flow lives in `agentbot.site.vfs_fra_flow` and is wired by the API/CLI
when targeting the VFS site.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Iterable, List

from agentbot.agents.booking import BookingProvider
from agentbot.agents.monitor import AvailabilityProvider
from agentbot.core.models import (
    AppointmentAvailability,
    AppointmentBookingRequest,
    AppointmentBookingResult,
)
from agentbot.data.session_store import SessionRecord
from agentbot.services.email import EmailInboxService
from agentbot.services.form_filler import FormFiller
from agentbot.services.http_client import HttpClient
from agentbot.utils.logging import get_logger


class ExampleAvailabilityProvider(AvailabilityProvider):
    """Example provider using HTTP polling."""

    def __init__(self, http_client: HttpClient, availability_endpoint: str) -> None:
        self.http_client = http_client
        self.availability_endpoint = availability_endpoint
        self.logger = get_logger(self.__class__.__name__)

    async def ensure_login(self, session: SessionRecord) -> None:
        # Placeholder: implement login logic using session.credentials.
        self.logger.debug("Ensuring login for session %s", session.session_id)
        await asyncio.sleep(0.1)

    async def check(self, session: SessionRecord) -> Iterable[AppointmentAvailability]:
        async with self.http_client.session(session.session_id) as client:
            response = await client.get(self.availability_endpoint)
            response.raise_for_status()
            response_data = response.json()

        slots: List[AppointmentAvailability] = []
        for slot_item in response_data.get("slots", []):
            slot_time = dt.datetime.fromisoformat(slot_item["start_time"])
            slots.append(
                AppointmentAvailability(
                    session_id=session.session_id,
                    slot_id=slot_item["id"],
                    slot_time=slot_time,
                    location=slot_item.get("location"),
                    extra=slot_item,
                )
            )
        return slots


class ExampleBookingProvider(BookingProvider):
    """Example booking provider using HTTP API + email OTP."""

    def __init__(
        self,
        http_client: HttpClient,
        *,
        booking_endpoint: str,
        submit_endpoint: str,
        email_service: EmailInboxService,
        form_filler: FormFiller,
    ) -> None:
        self.http_client = http_client
        self.booking_endpoint = booking_endpoint
        self.submit_endpoint = submit_endpoint
        self.email_service = email_service
        self.form_filler = form_filler
        self.logger = get_logger(self.__class__.__name__)

    async def book(self, request: AppointmentBookingRequest, session: SessionRecord) -> AppointmentBookingResult:
        async with self.http_client.session(session.session_id) as client:
            # Trigger verification code
            trigger_response = await client.post(self.booking_endpoint, json={"slot_id": request.slot.slot_id})
            trigger_response.raise_for_status()

            verification_code = await self.email_service.fetch_latest_code()
            if not verification_code:
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=False,
                    slot=request.slot,
                    message="No verification code received",
                )

            form_payload = self.form_filler.build_payload(request.user_profile)

            booking_payload = {
                "slot_id": request.slot.slot_id,
                "verification_code": verification_code,
                "user_profile": request.user_profile,
                "preferences": request.preferences,
                "form_payload": form_payload,
            }

            submit_response = await client.post(self.submit_endpoint, json=booking_payload)
            if submit_response.status_code >= 400:
                return AppointmentBookingResult(
                    session_id=request.session_id,
                    success=False,
                    slot=request.slot,
                    message=f"Booking failed with HTTP {submit_response.status_code}",
                    raw_response={"body": submit_response.text},
                )

            response_data = submit_response.json()
            confirmation = response_data.get("confirmation_number")
            return AppointmentBookingResult(
                session_id=request.session_id,
                success=True,
                slot=request.slot,
                confirmation_number=confirmation,
                raw_response=response_data,
            )
