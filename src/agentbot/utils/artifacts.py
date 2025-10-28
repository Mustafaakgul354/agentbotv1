"""Helpers to persist screenshots and artifacts for debugging/observability."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path


def artifacts_dir() -> Path:
    root = os.getenv("AGENTBOT_ARTIFACTS", "artifacts")
    path = Path(root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir(session_id: str) -> Path:
    path = artifacts_dir() / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_screenshot(page, session_id: str, label: str) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = session_dir(session_id) / f"{ts}-{label}.png"
    await page.screenshot(path=str(path))
    return path


