#!/usr/bin/env python3
"""
Example script demonstrating BrowserQL Hybrid Mode with LiveURL support.

This script shows how to:
1. Initialize a BrowserQL session with stealth features
2. Connect Playwright to the session via CDP
3. Get a LiveURL for monitoring and debugging
4. Perform browser actions using Playwright's API
5. Wait for LiveURL session to complete (optional)
6. Capture screenshots
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbot.browser.hybrid import HybridBrowserFactory
from agentbot.utils.logging import get_logger

logger = get_logger("HybridExample")


async def example_basic_usage():
    """Basic example: Initialize session and navigate to a URL."""
    logger.info("=== Basic Usage Example ===")
    
    # Create factory with BrowserQL configuration
    factory = HybridBrowserFactory(
        bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
        token="YOUR_BROWSERLESS_TOKEN",  # Replace with your token
        proxy="residential",  # Use residential proxy for better bot detection bypassing
        proxy_country="us",  # Set proxy country
        humanlike=True,  # Enable human-like behavior
        block_consent_modals=True,  # Auto-dismiss cookie banners
        enable_live_url=False,  # Disable LiveURL for this example
    )
    
    try:
        # Get a page for session
        async with factory.page("example-session") as page:
            logger.info("Session initialized! Navigating to example.com...")
            
            # Navigate to URL (protected by BQL stealth)
            await page.goto("https://www.example.com", wait_until="networkidle")
            
            logger.info("Current URL: %s", page.url)
            logger.info("Page title: %s", await page.title())
            
            # Perform some actions
            # await page.click('.some-button')
            # await page.fill('.some-input', 'Hello World')
            
            # Capture screenshot
            await factory.screenshot(
                "example-session",
                path="example-screenshot.png",
                full_page=False
            )
            
            logger.info("✅ Basic usage example completed!")
    
    finally:
        await factory.close_all()


async def example_with_cloudflare():
    """Example with Cloudflare verification."""
    logger.info("=== Cloudflare Verification Example ===")
    
    factory = HybridBrowserFactory(
        bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
        token="YOUR_BROWSERLESS_TOKEN",
        proxy="residential",  # Required for Cloudflare verification
        proxy_country="us",
        humanlike=True,
        block_consent_modals=True,
        enable_live_url=False,
    )
    
    try:
        # Initialize with Cloudflare verification
        async with factory.page("cloudflare-session", verify_cloudflare=True) as page:
            logger.info("Session initialized with Cloudflare verification!")
            
            # Navigate to a Cloudflare-protected site
            await page.goto("https://example-cloudflare-site.com", wait_until="networkidle")
            
            logger.info("Successfully bypassed Cloudflare!")
            logger.info("Current URL: %s", page.url)
            
            # Continue with automation...
            
            logger.info("✅ Cloudflare example completed!")
    
    finally:
        await factory.close_all()


async def example_with_live_url():
    """Example with LiveURL monitoring and waiting for user interaction."""
    logger.info("=== LiveURL Example ===")
    
    factory = HybridBrowserFactory(
        bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
        token="YOUR_BROWSERLESS_TOKEN",
        proxy="residential",
        proxy_country="us",
        humanlike=True,
        block_consent_modals=True,
        enable_live_url=True,  # Enable LiveURL
    )
    
    try:
        async with factory.page("live-session") as page:
            logger.info("Session initialized with LiveURL!")
            
            # The LiveURL is automatically logged when session is created
            live_url = factory.get_live_url("live-session")
            if live_url:
                logger.info("🔗 Share this URL with end-user: %s", live_url)
                logger.info("You can open this in a browser or embed in an iframe")
            
            # Navigate to a page
            await page.goto("https://www.example.com", wait_until="networkidle")
            
            # Perform some automation
            # await page.click('.some-button')
            
            # Option 1: Wait for user to finish interacting via LiveURL
            logger.info("Waiting for user to complete LiveURL session...")
            logger.info("(In production, user would interact via the LiveURL)")
            
            # Uncomment to actually wait for LiveURL completion:
            # await factory.wait_for_live_complete("live-session")
            
            # Option 2: Continue automation immediately
            logger.info("Continuing automation...")
            
            # Get final state
            logger.info("Final URL: %s", page.url)
            
            # Capture final screenshot
            await factory.screenshot(
                "live-session",
                path="live-session-screenshot.png"
            )
            
            logger.info("✅ LiveURL example completed!")
    
    finally:
        await factory.close_all()


async def example_complex_workflow():
    """Complex example: Multi-step workflow with error handling."""
    logger.info("=== Complex Workflow Example ===")
    
    factory = HybridBrowserFactory(
        bql_endpoint="https://production-sfo.browserless.io/chrome/bql",
        token="YOUR_BROWSERLESS_TOKEN",
        proxy="residential",
        proxy_country="us",
        humanlike=True,
        block_consent_modals=True,
        enable_live_url=True,
    )
    
    try:
        async with factory.page("workflow-session", verify_cloudflare=True) as page:
            logger.info("Step 1: Navigate to login page")
            await page.goto("https://example.com/login", wait_until="networkidle")
            
            logger.info("Step 2: Fill login form")
            await page.fill("input[name='email']", "user@example.com")
            await page.fill("input[name='password']", "password123")
            
            logger.info("Step 3: Submit form")
            await page.click("button[type='submit']")
            
            logger.info("Step 4: Wait for navigation")
            await page.wait_for_url("**/dashboard", timeout=30000)
            
            logger.info("Step 5: Capture proof of login")
            await factory.screenshot(
                "workflow-session",
                path="login-success.png",
                full_page=True
            )
            
            logger.info("Step 6: Navigate to booking page")
            await page.goto("https://example.com/book", wait_until="networkidle")
            
            logger.info("Step 7: Select appointment slot")
            await page.click("button[data-slot='slot-123']")
            await page.click("button:has-text('Confirm')")
            
            logger.info("Step 8: Wait for confirmation")
            await page.wait_for_selector(".confirmation-message", timeout=10000)
            
            logger.info("Step 9: Capture final screenshot")
            await factory.screenshot(
                "workflow-session",
                path="booking-confirmation.png"
            )
            
            logger.info("✅ Complex workflow completed successfully!")
    
    except Exception as e:
        logger.error("❌ Workflow failed: %s", e, exc_info=True)
        
        # Capture error screenshot
        try:
            await factory.screenshot(
                "workflow-session",
                path="error-screenshot.png"
            )
        except Exception:
            pass
    
    finally:
        await factory.close_all()


async def main():
    """Run all examples."""
    logger.info("Starting BrowserQL Hybrid Mode Examples")
    logger.info("=" * 60)
    
    # Note: Replace YOUR_BROWSERLESS_TOKEN with your actual token
    # You can get a token from: https://browserless.io
    
    try:
        # Run basic example
        await example_basic_usage()
        
        logger.info("\n" + "=" * 60 + "\n")
        
        # Run Cloudflare example
        # await example_with_cloudflare()
        
        # logger.info("\n" + "=" * 60 + "\n")
        
        # Run LiveURL example
        # await example_with_live_url()
        
        # logger.info("\n" + "=" * 60 + "\n")
        
        # Run complex workflow example
        # await example_complex_workflow()
        
    except Exception as e:
        logger.error("Example failed: %s", e, exc_info=True)
    
    logger.info("\n" + "=" * 60)
    logger.info("All examples completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

