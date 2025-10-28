"""Helpers for extracting one-time passwords from unstructured sources."""

from __future__ import annotations

import re
from typing import Optional


class OtpReader:
    """Simple OTP parser that extracts numeric codes from text blobs."""

    def __init__(self, pattern: str = r"\b(\d{4,8})\b") -> None:
        self._regex = re.compile(pattern)

    def parse(self, text: str) -> Optional[str]:
        match = self._regex.search(text)
        return match.group(1) if match else None

