"""FastAPI application exposing runtime control endpoints."""

from __future__ import annotations

from pathlib import Path

import os

from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List

from agentbot.agents.booking import BookingAgent
from agentbot.agents.monitor import MonitorAgent
from agentbot.browser.humanlike import set_humanlike_mouse_config
from agentbot.core.message_bus import MessageBus
from agentbot.core.message_bus_redis import RedisMessageBus  # optional
from agentbot.core.locks_redis import RedisLockManager
from agentbot.core.runtime import AgentRuntime
from agentbot.core.settings import RuntimeSettings
from agentbot.data.session_store import SessionRecord, SessionStore
from agentbot.app.models import AppState, SessionSummary
from agentbot.services import AuditLogger, EmailInboxService, FormFiller, HttpClient
from agentbot.services.form_filler import FieldMapping
from agentbot.utils.env import get_bool_env, get_list_env
from agentbot.utils.logging import get_logger


logger = get_logger("AgentAPI")


def _load_form_mapping(path: Path | None) -> FormFiller:
    if not path or not path.exists():
        return FormFiller([])
    import yaml

    data = yaml.safe_load(path.read_text()) or {}
    fields = [FieldMapping(**item) for item in data.get("fields", [])]
    return FormFiller(fields)


def create_app(config_path: Path) -> FastAPI:
    settings = RuntimeSettings.from_file(config_path)
    set_humanlike_mouse_config(
        settings.humanlike_mouse.model_dump() if settings.humanlike_mouse else None
    )
    session_store = SessionStore(settings.session_store_path)
    # Select message bus backend
    bus_backend = os.getenv("AGENTBOT_BUS", "memory").lower()
    if bus_backend == "redis":
        message_bus = RedisMessageBus(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    else:
        message_bus = MessageBus()
    http_client = HttpClient(str(settings.base_url))
    email_service = EmailInboxService(**settings.email.model_dump())
    form_filler = _load_form_mapping(settings.form_mapping_path)

    # Optional LLM wiring
    llm = None
    try:
        llm_provider = os.getenv("AGENTBOT_LLM", "").lower()
        if llm_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                from agentbot.services.llm import OpenAIClient  # lazy import

                llm = OpenAIClient(api_key=api_key, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
            else:
                logger.warning("AGENTBOT_LLM=openai but OPENAI_API_KEY not set; LLM disabled")
    except Exception as exc:
        logger.warning("LLM disabled: %s", exc)

    audit_logger = AuditLogger()
    runtime = AgentRuntime(session_store=session_store, message_bus=message_bus, audit_logger=audit_logger)

    # Site providers: default to VFS Playwright or BrowserQL
    from agentbot.browser.play import BrowserFactory
    from agentbot.browser.browserql import BrowserQLFactory
    from agentbot.browser.hybrid import HybridBrowserFactory
    from agentbot.site.vfs_fra_flow import (
        VfsAvailabilityProvider,
        VfsBookingProvider,
    )

    # Use BrowserQL if configured, otherwise fall back to Playwright
    #if settings.browserql and settings.browserql.endpoint:
    #    endpoint = str(settings.browserql.endpoint)
    #    token = settings.browserql.token or os.getenv("BROWSERQL_TOKEN")
    #    
    #    # Check for hybrid mode (BQL + Playwright via CDP)
    #    use_hybrid = settings.browserql.hybrid
    #    
    #    if use_hybrid:
    #        browser = HybridBrowserFactory(
    #            bql_endpoint=endpoint,
    #            token=token,
    #            proxy=settings.browserql.proxy,
    #            proxy_country=settings.browserql.proxy_country,
    #            humanlike=settings.browserql.humanlike,
    #            block_consent_modals=settings.browserql.block_consent_modals,
    #            hybrid=use_hybrid,
    #        )
    #        logger.info("Using Hybrid mode (BQL stealth + Playwright): %s", endpoint)
    #    else:
    #        browser = BrowserQLFactory(
    #            endpoint=endpoint,
    #            token=token,
    #            proxy=settings.browserql.proxy,
    #            proxy_country=settings.browserql.proxy_country,
    #            humanlike=settings.browserql.humanlike,
    #            block_consent_modals=settings.browserql.block_consent_modals,
    #        )
    #        logger.info("Using BrowserQL mode: %s", endpoint)
    #else:
    #    headless = get_bool_env("AGENTBOT_HEADLESS", default=True)
    #    launch_args = get_list_env("AGENTBOT_BROWSER_ARGS")
    #    browser = BrowserFactory(headless=headless, extra_launch_args=launch_args)
    #    logger.info("Using Playwright BrowserFactory (headless=%s)", headless)
    #    if launch_args:
    #        logger.info("Custom Chromium flags: %s", launch_args)
    headless = get_bool_env("AGENTBOT_HEADLESS", default=True)
    launch_args = get_list_env("AGENTBOT_BROWSER_ARGS")
    browser = BrowserFactory(headless=headless, extra_launch_args=launch_args)
    logger.info("Using Playwright BrowserFactory (headless=%s)", headless)
    if launch_args:
        logger.info("Custom Chromium flags: %s", launch_args)
    
    lock_manager = RedisLockManager() if bus_backend == "redis" else None

    def monitor_factory(config, record: SessionRecord) -> MonitorAgent:
        provider = VfsAvailabilityProvider(browser, email_service=email_service, llm=llm)
        return MonitorAgent(
            config,
            message_bus=message_bus,
            session_record=record,
            provider=provider,
            planner=runtime.planner,
        )

    def booking_factory(config, record: SessionRecord) -> BookingAgent:
        provider = VfsBookingProvider(browser, email_service=email_service, form_filler=form_filler)
        return BookingAgent(
            config,
            message_bus=message_bus,
            session_record=record,
            provider=provider,
            lock_manager=lock_manager,
            planner=runtime.planner,
            audit_logger=audit_logger,
        )

    app = FastAPI(title="AgentBot Runtime")

    @app.on_event("startup")
    async def _startup() -> None:  # pragma: no cover
        await runtime.bootstrap(monitor_factory, booking_factory)
        await runtime.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover
        await runtime.stop()
        await http_client.close_all()

    @app.get("/")
    async def root() -> dict:
        """Root endpoint with API information."""
        sessions = len(await session_store.list_sessions())
        return {
            "name": "AgentBot Runtime API",
            "version": "1.0.0",
            "status": "running",
            "sessions": sessions,
            "endpoints": {
                "health": "/health",
                "api_docs": "/docs",
                "api_redoc": "/redoc",
                "sessions": "/sessions",
                "control_start": "/control/start",
                "control_stop": "/control/stop",
            },
            "message": "AgentBot is running. Visit /docs for API documentation."
        }

    @app.get("/health", response_model=AppState)
    async def health() -> AppState:
        runtime: AgentRuntime | None = app_state.get("runtime")
        sessions = []
        return AppState(started=True, sessions=sessions)

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    @app.get("/favicon.ico")
    async def favicon() -> None:
        """Handle favicon and apple touch icon requests to prevent 404 errors in logs."""
        from fastapi.responses import Response
        return Response(status_code=204)  # No Content

    @app.post("/sessions")
    async def upsert_session(payload: NewSession) -> dict:
        record = SessionRecord(**payload.model_dump())
        await session_store.upsert(record)
        return {"ok": True}

    @app.post("/control/start")
    async def start_runtime() -> dict:
        await runtime.start()
        return {"ok": True}

    @app.post("/control/stop")
    async def stop_runtime() -> dict:
        await runtime.stop()
        return {"ok": True}

    return app


# Default ASGI app when run via `uvicorn agentbot.app.main:app` with env AGENTBOT_CONFIG

config_env = os.getenv("AGENTBOT_CONFIG", "config/runtime.example.yml")
app = create_app(Path(config_env))
