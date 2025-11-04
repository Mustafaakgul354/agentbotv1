"""Structured audit logger writing JSON Lines for critical events."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class AuditLogger:
    """Persist structured audit trail entries for observability and compliance."""

    def __init__(self, path: Optional[Path] = None) -> None:
        target = path or Path(os.getenv("AGENTBOT_AUDIT_LOG", "artifacts/audit.log"))
        target.parent.mkdir(parents=True, exist_ok=True)
        self._path = target
        self._lock = asyncio.Lock()

    async def log(self, *, event: str, session_id: str, payload: Dict[str, Any]) -> None:
        record = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": event,
            "session_id": session_id,
            "payload": payload,
        }
        async with self._lock:
            await asyncio.to_thread(self._append_line, record)

    def _append_line(self, record: Dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True))
            fh.write("\n")

