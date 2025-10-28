"""Form filling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Protocol


class PageSession(Protocol):
    """Protocol representing the methods we need from a headless browser page."""

    async def fill(self, selector: str, value: str) -> None:
        ...

    async def click(self, selector: str) -> None:
        ...


@dataclass
class FieldMapping:
    selector: str
    value_key: str


class FormFiller:
    """Maps structured data to DOM selectors."""

    def __init__(self, mapping: Iterable[FieldMapping]) -> None:
        self._mapping = list(mapping)

    async def populate(self, page: PageSession, data: Mapping[str, Any]) -> None:
        for field in self._mapping:
            value = data.get(field.value_key)
            if value is None:
                continue
            selectors = [s.strip() for s in field.selector.split("||")] if "||" in field.selector else [field.selector]
            for sel in selectors:
                try:
                    await page.fill(sel, str(value))
                    break
                except Exception:
                    continue

    def build_payload(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        """Create a mapping of selectors to values for API-based submissions."""
        payload: Dict[str, Any] = {}
        for field in self._mapping:
            if field.value_key in data:
                payload[field.selector] = data[field.value_key]
        return payload

