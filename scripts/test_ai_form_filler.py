#!/usr/bin/env python3
"""Test script for AI-powered form filling.

This script demonstrates how the AI page analyzer works:
1. Navigate to a URL
2. Analyze the page structure with AI
3. Display identified form fields
4. Fill the form with session data
5. Capture screenshots at each step
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbot.browser.play import BrowserFactory
from agentbot.browser.hybrid import HybridBrowserFactory
from agentbot.data.session_store import SessionStore
from agentbot.services.email import EmailInboxService
from agentbot.services.llm import OpenAIClient
from agentbot.services.page_analyzer import PageAnalyzer
from agentbot.site.vfs_fra_flow import VfsAvailabilityProvider
from agentbot.utils.logging import get_logger
from agentbot.utils.env import get_env

logger = get_logger("TestAIFormFiller")


async def test_page_analyzer_only(url: str = "https://visa.vfsglobal.com/tur/tr/fra/login"):
    """Test the page analyzer in isolation."""
    logger.info("=" * 80)
    logger.info("TEST 1: Page Analyzer Only (No Form Filling)")
    logger.info("=" * 80)
    
    # Get API key
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set. Please set it in your environment.")
        return
    
    # Create LLM client
    llm = OpenAIClient(api_key=api_key, model="gpt-4o-mini")
    
    # Create page analyzer
    analyzer = PageAnalyzer(llm)
    
    # Create browser (use simple Playwright for this test)
    browser = BrowserFactory(headless=False, user_data_root=Path(".user_data"))
    
    async with browser.page("test-analyzer") as page:
        logger.info(f"Navigating to: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Wait for page to load
        await asyncio.sleep(3)
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # Get HTML content
        logger.info("Extracting page HTML...")
        html_content = await page.content()
        
        # Save HTML for inspection
        html_path = Path("artifacts/test-analyzer/page-content.html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"HTML saved to: {html_path}")
        
        # Analyze with AI
        logger.info("Analyzing page with AI...")
        analysis = await analyzer.analyze_page(html_content, page.url)
        
        # Display results
        logger.info("\n" + "=" * 80)
        logger.info("ANALYSIS RESULTS")
        logger.info("=" * 80)
        logger.info(f"URL: {analysis.url}")
        logger.info(f"Form Fields: {len(analysis.form_fields)}")
        logger.info(f"Actions: {len(analysis.action_sequence)}")
        logger.info(f"Has CAPTCHA: {analysis.has_captcha}")
        logger.info(f"Has OTP: {analysis.has_otp}")
        
        if analysis.form_fields:
            logger.info("\n📝 IDENTIFIED FORM FIELDS:")
            for i, field in enumerate(analysis.form_fields, 1):
                logger.info(f"\n  {i}. {field.purpose.value.upper()}")
                logger.info(f"     Selector: {field.selector}")
                logger.info(f"     Type: {field.field_type}")
                logger.info(f"     Label: {field.label or 'N/A'}")
                logger.info(f"     Required: {field.required}")
                logger.info(f"     Confidence: {field.confidence:.2f}")
        
        if analysis.action_sequence:
            logger.info("\n🔄 ACTION SEQUENCE:")
            for action in analysis.action_sequence:
                logger.info(f"\n  {action.order}. {action.action_type.value.upper()}")
                logger.info(f"     Description: {action.description}")
                logger.info(f"     Selector: {action.selector}")
                if action.value_source:
                    logger.info(f"     Value from: {action.value_source}")
                if action.wait_after:
                    logger.info(f"     Wait after: {action.wait_after}ms")
        
        if analysis.submit_button:
            logger.info(f"\n✅ SUBMIT BUTTON: {analysis.submit_button.selector}")
        
        logger.info("\n" + "=" * 80)
        logger.info("Press Ctrl+C to exit...")
        await asyncio.sleep(30)


async def test_full_ai_login():
    """Test the full AI-powered login flow."""
    logger.info("=" * 80)
    logger.info("TEST 2: Full AI-Powered Login Flow")
    logger.info("=" * 80)
    
    # Load session
    session_store = SessionStore(Path("config/session_store.json"))
    sessions = await session_store.list_sessions()
    
    if not sessions:
        logger.error("No sessions found in config/session_store.json")
        logger.error("Please create a session first.")
        return
    
    session = sessions[0]
    logger.info(f"Testing login for session: {session.session_id}")
    logger.info(f"User: {session.email}")
    
    # Get API key
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set. Please set it in your environment.")
        return
    
    # Create LLM client
    llm = OpenAIClient(api_key=api_key, model="gpt-4o-mini")
    
    # Create browser (headless=False to see what's happening)
    browser = BrowserFactory(
        headless=False,
        user_data_root=Path(".user_data"),
    )
    
    # Create email service (dummy for testing)
    email_service = EmailInboxService(
        host=get_env("EMAIL_HOST", "imap.example.com"),
        port=int(get_env("EMAIL_PORT", "993")),
        username=get_env("EMAIL_USERNAME", "dummy"),
        password=get_env("EMAIL_PASSWORD", "dummy"),
        folder="INBOX",
        use_ssl=True,
    )
    
    # Create provider with AI form filling enabled
    provider = VfsAvailabilityProvider(
        browser,
        email_service=email_service,
        llm=llm,
        enable_ai_form_filling=True,  # Enable AI!
        session_store=session_store,  # Pass store for fresh data
    )
    
    try:
        logger.info("\n🤖 Starting AI-powered login flow...")
        await provider.ensure_login(session)
        logger.info("\n✅ Login successful!")
        
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
        logger.error(f"\n❌ Login failed: {e}", exc_info=True)
        
        # Show artifacts location
        artifacts_dir = Path("artifacts") / session.session_id
        if artifacts_dir.exists():
            logger.error(f"\n📸 Debug artifacts saved to: {artifacts_dir}")
            logger.error("Check the screenshots and HTML to see what went wrong")
    
    logger.info("\n" + "=" * 80)
    logger.info("Press Ctrl+C to exit...")
    await asyncio.sleep(60)


async def test_hybrid_browser_ai():
    """Test AI form filling with HybridBrowser (BQL + Playwright)."""
    logger.info("=" * 80)
    logger.info("TEST 3: AI Form Filling with HybridBrowser (BQL + Playwright)")
    logger.info("=" * 80)
    
    # Get configuration
    bql_endpoint = get_env("BROWSERQL_ENDPOINT")
    bql_token = get_env("BROWSERQL_TOKEN")
    api_key = get_env("OPENAI_API_KEY")
    
    if not bql_endpoint or not bql_token:
        logger.error("BrowserQL configuration not set.")
        logger.error("Please set BROWSERQL_ENDPOINT and BROWSERQL_TOKEN")
        return
    
    if not api_key:
        logger.error("OPENAI_API_KEY not set.")
        return
    
    # Load session
    session_store = SessionStore(Path("config/session_store.json"))
    sessions = await session_store.list_sessions()
    
    if not sessions:
        logger.error("No sessions found in config/session_store.json")
        return
    
    session = sessions[0]
    logger.info(f"Testing login for session: {session.session_id}")
    
    # Create LLM client
    llm = OpenAIClient(api_key=api_key, model="gpt-4o-mini")
    
    # Create HybridBrowser factory
    browser = HybridBrowserFactory(
        bql_endpoint=bql_endpoint,
        token=bql_token,
        proxy="residential",
        proxy_country="tr",
        humanlike=True,
        block_consent_modals=True,
        enable_live_url=False,
    )
    
    # Create email service
    email_service = EmailInboxService(
        host=get_env("EMAIL_HOST", "imap.example.com"),
        port=int(get_env("EMAIL_PORT", "993")),
        username=get_env("EMAIL_USERNAME", "dummy"),
        password=get_env("EMAIL_PASSWORD", "dummy"),
        folder="INBOX",
        use_ssl=True,
    )
    
    # Create provider with AI
    provider = VfsAvailabilityProvider(
        browser,
        email_service=email_service,
        llm=llm,
        enable_ai_form_filling=True,
        session_store=session_store,  # Pass store for fresh data
    )
    
    try:
        logger.info("\n🚀 Starting AI + HybridBrowser login flow...")
        await provider.ensure_login(session)
        logger.info("\n✅ Login successful with hybrid browser + AI!")
        
        artifacts_dir = Path("artifacts") / session.session_id
        if artifacts_dir.exists():
            logger.info(f"\n📸 Artifacts saved to: {artifacts_dir}")
    
    except Exception as e:
        logger.error(f"\n❌ Login failed: {e}", exc_info=True)
    
    finally:
        await browser.close_all()
    
    logger.info("\n" + "=" * 80)


async def main():
    """Run all tests."""
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()
        if test_name == "analyzer":
            await test_page_analyzer_only()
        elif test_name == "login":
            await test_full_ai_login()
        elif test_name == "hybrid":
            await test_hybrid_browser_ai()
        else:
            logger.error(f"Unknown test: {test_name}")
            logger.info("Available tests: analyzer, login, hybrid")
    else:
        # Run default test
        logger.info("Running default test: analyzer")
        logger.info("Usage: python test_ai_form_filler.py [analyzer|login|hybrid]")
        logger.info("")
        await test_page_analyzer_only()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")

