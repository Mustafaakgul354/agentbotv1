"""CLI entrypoint to launch the agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agentbot.agents.booking import BookingAgent
from agentbot.agents.monitor import MonitorAgent
from agentbot.core.message_bus import MessageBus
from agentbot.core.runtime import AgentRuntime
from agentbot.core.settings import RuntimeSettings
from agentbot.data.session_store import SessionRecord, SessionStore
from agentbot.services import EmailInboxService, FormFiller, HttpClient
from agentbot.services.form_filler import FieldMapping
from agentbot.utils.logging import get_logger


logger = get_logger("AgentCLI")


def _load_form_mapping(path: Path | None) -> FormFiller:
    if path is None or not path.exists():
        logger.warning("No form mapping provided; booking provider will send raw profile payload.")
        return FormFiller([])

    mapping_data = json.loads(path.read_text()) if path.suffix.lower() == ".json" else _load_yaml(path)
    fields = [
        FieldMapping(selector=field_item["selector"], value_key=field_item["value_key"])
        for field_item in mapping_data.get("fields", [])
    ]
    return FormFiller(fields)


def _load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text()) or {}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-agent appointment booking runtime.")
    parser.add_argument("--config", type=Path, default=Path("config/runtime.example.yml"), help="Path to runtime YAML")
    cli_args = parser.parse_args()

    settings = RuntimeSettings.from_file(cli_args.config)
    session_store = SessionStore(settings.session_store_path)
    message_bus = MessageBus()
    http_client = HttpClient(str(settings.base_url))
    email_service = EmailInboxService(**settings.email.model_dump())
    form_filler = _load_form_mapping(settings.form_mapping_path)

    runtime = AgentRuntime(session_store=session_store, message_bus=message_bus)

    from agentbot.browser.play import BrowserFactory
    from agentbot.browser.browserql import BrowserQLFactory
    from agentbot.site.vfs_fra_flow import VfsAvailabilityProvider, VfsBookingProvider
    import os

    # Use BrowserQL if configured, otherwise fall back to Playwright
    if settings.browserql and settings.browserql.endpoint:
        endpoint = str(settings.browserql.endpoint)
        token = settings.browserql.token or os.getenv("BROWSERQL_TOKEN")
        browser = BrowserQLFactory(
            endpoint=endpoint,
            token=token,
            proxy=settings.browserql.proxy,
            proxy_country=settings.browserql.proxy_country,
            humanlike=settings.browserql.humanlike,
            block_consent_modals=settings.browserql.block_consent_modals,
        )
        logger.info("Using BrowserQL with endpoint: %s", endpoint)
    else:
        browser = BrowserFactory(headless=False)
        logger.info("Using Playwright BrowserFactory")

    def monitor_factory(agent_config, session_record: SessionRecord) -> MonitorAgent:
        provider = VfsAvailabilityProvider(browser, email_service=email_service)
        effective_config = agent_config.model_copy(
            update={"poll_interval_seconds": agent_config.poll_interval_seconds or settings.poll_interval_seconds}
        )
        return MonitorAgent(
            effective_config,
            message_bus=message_bus,
            session_record=session_record,
            provider=provider,
        )

    def booking_factory(agent_config, session_record: SessionRecord) -> BookingAgent:
        from agentbot.core.locks_redis import RedisLockManager

        provider = VfsBookingProvider(browser, email_service=email_service)
        lock_manager = RedisLockManager()
        return BookingAgent(
            agent_config,
            message_bus=message_bus,
            session_record=session_record,
            provider=provider,
            lock_manager=lock_manager,
        )

    await runtime.bootstrap(monitor_factory, booking_factory)
    try:
        await runtime.run_forever()
    finally:
        await http_client.close_all()


if __name__ == "__main__":
    asyncio.run(main())
