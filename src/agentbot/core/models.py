"""Data models shared across the AgentBot runtime."""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Message types flowing through the system."""

    APPOINTMENT_AVAILABLE = "appointment.available"
    BOOKING_REQUEST = "booking.request"
    BOOKING_RESULT = "booking.result"
    HEARTBEAT = "agent.heartbeat"
    RUNTIME_ALERT = "runtime.alert"


class AgentConfig(BaseModel):
    """Configuration for a single agent instance."""

    session_id: str
    user_id: str
    poll_interval_seconds: int = Field(default=30, ge=5)
    timezone: str = "UTC"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AppointmentAvailability(BaseModel):
    """Represents an available appointment slot."""

    session_id: str
    slot_id: str
    slot_time: dt.datetime
    location: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class AppointmentBookingRequest(BaseModel):
    """Request for a booking agent to attempt a reservation."""

    session_id: str
    slot: AppointmentAvailability
    user_profile: Dict[str, Any]
    preferences: Dict[str, Any] = Field(default_factory=dict)


class AppointmentBookingResult(BaseModel):
    """Outcome of a booking attempt."""

    session_id: str
    success: bool
    confirmation_number: Optional[str] = None
    message: Optional[str] = None
    slot: Optional[AppointmentAvailability] = None
    raw_response: Optional[Dict[str, Any]] = None


class EventEnvelope(BaseModel):
    """Wrapper to transport events safely through the message bus."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    type: EventType
    session_id: str
    payload: Dict[str, Any]
    trace_id: Optional[str] = None

