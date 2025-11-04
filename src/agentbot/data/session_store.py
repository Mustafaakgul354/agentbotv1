"""Simple JSON-backed session store."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, ValidationError

from agentbot.core.models import AgentConfig


class SessionRecord(BaseModel):
    """Stored user session definition."""

    session_id: str
    user_id: str
    email: str
    credentials: Dict[str, Any] = Field(default_factory=dict)
    profile: Dict[str, Any] = Field(default_factory=dict)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    def to_agent_config(self, default_poll: int = 30) -> AgentConfig:
        poll = int(self.preferences.get("poll_interval_seconds", default_poll))
        return AgentConfig(
            session_id=self.session_id,
            user_id=self.user_id,
            poll_interval_seconds=poll,
            metadata=self.metadata | {"email": self.email},
        )


class SessionStore:
    """Minimal JSON file session persistence with async-friendly API."""

    def __init__(self, path: Path, *, encryption_key: Optional[str] = None) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._records: Dict[str, SessionRecord] = {}
        self._fernet = self._init_fernet(encryption_key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._load()

    def _init_fernet(self, key: Optional[str]) -> Optional["Fernet"]:
        key = key or os.getenv("AGENTBOT_SESSION_KEY")
        if not key:
            return None
        from cryptography.fernet import Fernet

        if isinstance(key, str):
            key_bytes = key.encode("utf-8")
        else:
            key_bytes = key
        try:
            return Fernet(key_bytes)
        except Exception as exc:
            raise ValueError("Invalid AGENTBOT_SESSION_KEY provided for SessionStore encryption") from exc

    def _load(self) -> None:
        raw = self._path.read_bytes()
        if self._fernet:
            from cryptography.fernet import InvalidToken

            try:
                raw = self._fernet.decrypt(raw)
            except InvalidToken as exc:
                raise ValueError("Unable to decrypt session store with provided key") from exc
        data = json.loads(raw.decode("utf-8"))
        records = {}
        for item in data:
            try:
                record = SessionRecord(**item)
            except ValidationError as exc:
                raise ValueError(f"Invalid session record: {exc}") from exc
            records[record.session_id] = record
        self._records = records

    def _dump(self) -> None:
        serialized = [record.model_dump(mode="json") for record in self._records.values()]
        payload = json.dumps(serialized, indent=2).encode("utf-8")
        if self._fernet:
            payload = self._fernet.encrypt(payload)
        self._path.write_bytes(payload)

    async def list_sessions(self) -> List[SessionRecord]:
        async with self._lock:
            return list(self._records.values())

    async def get(self, session_id: str) -> Optional[SessionRecord]:
        async with self._lock:
            return self._records.get(session_id)

    async def upsert(self, record: SessionRecord) -> None:
        async with self._lock:
            self._records[record.session_id] = record
            self._dump()

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            if session_id in self._records:
                del self._records[session_id]
                self._dump()

    async def iter_agent_configs(self, *, default_poll: int = 30) -> Iterable[AgentConfig]:
        sessions = await self.list_sessions()
        for session in sessions:
            yield session.to_agent_config(default_poll=default_poll)
