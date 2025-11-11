#!/usr/bin/env python3
"""Debug script to test VFS login flow with detailed logging."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbot.browser.play import BrowserFactory
from agentbot.data.session_store import SessionStore
from agentbot.services.email import EmailInboxService
from agentbot.site.vfs_fra_flow import VfsAvailabilityProvider
from agentbot.utils.logging import get_logger

logger = get_logger("DebugLogin")


async def main():
    """Run debug login test."""
    # Load session
    session_store = SessionStore(Path("config/session_store.json"))
    sessions = await session_store.list_sessions()
    
    if not sessions:
        logger.error("No sessions found in config/session_store.json")
        return
    
    session = sessions[0]
    logger.info(f"Testing login for session: {session.session_id}")
    logger.info(f"User: {session.email}")
    
    # Create browser (headless=True for headless mode)
    browser = BrowserFactory(
        headless=True,  # Set to True for headless mode
        user_data_root=Path(".user_data"),
    )
    
    # Create email service (dummy for now)
    email_service = EmailInboxService(
        host="imap.example.com",
        port=993,
        username="dummy",
        password="dummy",
        folder="INBOX",
        use_ssl=True,
    )
    
    # Create provider
    provider = VfsAvailabilityProvider(browser, email_service=email_service)
    
    try:
        logger.info("Starting login flow...")
        await provider.ensure_login(session)
        logger.info("✅ Login successful!")
        
        # Check artifacts
        artifacts_dir = Path("artifacts") / session.session_id
        if artifacts_dir.exists():
            logger.info(f"\n📸 Screenshots saved to: {artifacts_dir}")
            for screenshot in sorted(artifacts_dir.glob("*.png")):
                logger.info(f"  - {screenshot.name}")
            
            html_file = artifacts_dir / "page-content.html"
            if html_file.exists():
                logger.info(f"\n📄 Page HTML saved to: {html_file}")
        
    except Exception as e:
        logger.error(f"❌ Login failed: {e}", exc_info=True)
        
        # Show artifacts location
        artifacts_dir = Path("artifacts") / session.session_id
        if artifacts_dir.exists():
            logger.error(f"\n📸 Debug artifacts saved to: {artifacts_dir}")
            logger.error("Check the screenshots and HTML to see what went wrong")
    
    logger.info("\nPress Ctrl+C to exit...")
    await asyncio.sleep(300)  # Keep browser open for 5 minutes


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

