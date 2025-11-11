"""Runtime settings loader."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError


class EmailSettings(BaseModel):
    host: str
    port: int = 993
    username: str
    password: str
    folder: str = "INBOX"
    use_ssl: bool = True


class BrowserQLSettings(BaseModel):
    """BrowserQL/Browserless.io settings."""
    endpoint: Optional[HttpUrl] = None
    token: Optional[str] = None  # Browserless.io token (can also use BROWSERQL_TOKEN env var)
    proxy: Optional[str] = None  # "residential" or "datacenter"
    proxy_country: Optional[str] = None  # e.g., "tr", "us"
    humanlike: bool = True
    block_consent_modals: bool = True
    hybrid: bool = False  # If True, use HybridBrowserFactory (BQL + Playwright via CDP)


class HumanlikeMouseSettings(BaseModel):
    """Configures imperfect cursor motion for Playwright interactions."""

    enabled: bool = True
    move_duration_range: Tuple[float, float] = (0.45, 0.9)
    hover_delay_range: Tuple[float, float] = (0.08, 0.2)
    press_duration_range: Tuple[float, float] = (0.05, 0.12)
    curvature_range: Tuple[float, float] = (0.12, 0.35)
    noise: float = 2.2
    steps_range: Tuple[int, int] = (18, 32)


class RuntimeSettings(BaseModel):
    base_url: HttpUrl
    availability_endpoint: str
    booking_endpoint: str
    submit_endpoint: str
    session_store_path: Path = Field(default=Path("session_store.json"))
    poll_interval_seconds: int = 30
    email: EmailSettings
    form_mapping_path: Optional[Path] = None
    browserql: Optional[BrowserQLSettings] = None
    humanlike_mouse: Optional[HumanlikeMouseSettings] = None

    @classmethod
    def from_file(cls, path: Path) -> "RuntimeSettings":
        data = yaml.safe_load(path.read_text())
        try:
            settings = cls.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid runtime settings: {exc}") from exc
        if not settings.session_store_path.is_absolute():
            settings.session_store_path = (path.parent / settings.session_store_path).resolve()
        if settings.form_mapping_path and not settings.form_mapping_path.is_absolute():
            settings.form_mapping_path = (path.parent / settings.form_mapping_path).resolve()
        return settings
