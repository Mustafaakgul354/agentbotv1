"""Simple planner maintaining per-session state machines."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict, Optional

from agentbot.core.models import AppointmentAvailability, AppointmentBookingResult


class SessionState(enum.Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    CLAIMING = "claiming"
    BOOKING = "booking"
    BOOKED = "booked"
    FAILED = "failed"


@dataclass
class SessionFSM:
    state: SessionState = SessionState.IDLE
    last_slot: Optional[AppointmentAvailability] = None
    last_result: Optional[AppointmentBookingResult] = None


class AgentPlanner:
    """Tracking helper that updates finite-state machines per session."""

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionFSM] = {}

    def on_monitoring(self, session_id: str) -> None:
        fsm = self._sessions.setdefault(session_id, SessionFSM())
        fsm.state = SessionState.MONITORING

    def on_availability(self, session_id: str, slot: AppointmentAvailability) -> None:
        fsm = self._sessions.setdefault(session_id, SessionFSM())
        fsm.state = SessionState.CLAIMING
        fsm.last_slot = slot

    def on_booking_result(self, session_id: str, result: AppointmentBookingResult) -> SessionState:
        fsm = self._sessions.setdefault(session_id, SessionFSM())
        fsm.last_result = result
        if result.success:
            fsm.state = SessionState.BOOKED
        else:
            fsm.state = SessionState.FAILED
        return fsm.state

    def on_booking_attempt(self, session_id: str) -> None:
        fsm = self._sessions.setdefault(session_id, SessionFSM())
        fsm.state = SessionState.BOOKING

    def reset(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id] = SessionFSM(state=SessionState.IDLE)

    def get_state(self, session_id: str) -> SessionState:
        return self._sessions.get(session_id, SessionFSM()).state
