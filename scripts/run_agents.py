"""CLI entrypoint to launch the agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agentbot.agents.booking import BookingAgent
from agentbot.agents.monitor import MonitorAgent
from agentbot.browser.humanlike import set_humanlike_mouse_config
from agentbot.core.message_bus import MessageBus
from agentbot.core.runtime import AgentRuntime
from agentbot.core.settings import RuntimeSettings
from agentbot.data.session_store import SessionRecord, SessionStore
from agentbot.services import AuditLogger, EmailInboxService, FormFiller, HttpClient
from agentbot.services.form_filler import FieldMapping
from agentbot.utils.env import get_bool_env, get_list_env
from agentbot.utils.logging import get_logger


logger = get_logger("AgentCLI")


def _load_form_mapping(path: Path | None) -> FormFiller:
    if path is None or not path.exists():
        logger.warning("No form mapping provided; booking provider will send raw profile payload.")
        return FormFiller([])

    data = json.loads(path.read_text()) if path.suffix.lower() == ".json" else _load_yaml(path)
    fields = [
        FieldMapping(selector=item["selector"], value_key=item["value_key"])
        for item in data.get("fields", [])
    ]
    return FormFiller(fields)


def _load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text()) or {}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-agent appointment booking runtime.")
    parser.add_argument("--config", type=Path, default=Path("config/runtime.example.yml"), help="Path to runtime YAML")
    args = parser.parse_args()

    settings = RuntimeSettings.from_file(args.config)
    set_humanlike_mouse_config(
        settings.humanlike_mouse.model_dump() if settings.humanlike_mouse else None
    )
    session_store = SessionStore(settings.session_store_path)
    message_bus = MessageBus()
    http_client = HttpClient(str(settings.base_url))
    email_service = EmailInboxService(**settings.email.model_dump())
    form_filler = _load_form_mapping(settings.form_mapping_path)
    audit_logger = AuditLogger()

    runtime = AgentRuntime(session_store=session_store, message_bus=message_bus, audit_logger=audit_logger)

    from agentbot.browser.play import BrowserFactory
    from agentbot.browser.browserql import BrowserQLFactory
    from agentbot.browser.hybrid import HybridBrowserFactory
    from agentbot.site.vfs_fra_flow import VfsAvailabilityProvider, VfsBookingProvider
    import os

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

    def monitor_factory(config, record: SessionRecord) -> MonitorAgent:
        provider = VfsAvailabilityProvider(browser, email_service=email_service)
        effective_config = config.model_copy(
            update={"poll_interval_seconds": config.poll_interval_seconds or settings.poll_interval_seconds}
        )
        return MonitorAgent(
            effective_config,
            message_bus=message_bus,
            session_record=record,
            provider=provider,
            planner=runtime.planner,
        )

    def booking_factory(config, record: SessionRecord) -> BookingAgent:
        from agentbot.core.locks_redis import RedisLockManager

        provider = VfsBookingProvider(browser, email_service=email_service)
        lock_manager = RedisLockManager()
        return BookingAgent(
            config,
            message_bus=message_bus,
            session_record=record,
            provider=provider,
            lock_manager=lock_manager,
            planner=runtime.planner,
            audit_logger=audit_logger,
        )

    await runtime.bootstrap(monitor_factory, booking_factory)
    try:
        await runtime.run_forever()
    finally:
        await http_client.close_all()


if __name__ == "__main__":
    asyncio.run(main())
