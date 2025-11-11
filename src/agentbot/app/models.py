from pydantic import BaseModel
from typing import List

class SessionSummary(BaseModel):
    session_id: str
    is_running: bool
    status: str

class AppState(BaseModel):
    started: bool
    sessions: List[SessionSummary]
