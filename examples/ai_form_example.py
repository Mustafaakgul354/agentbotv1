#!/usr/bin/env python3
"""Simple example of AI-powered form filling.

This example shows how to use the AI form analyzer to automatically
fill web forms without hardcoded selectors.
"""

import asyncio
from pathlib import Path

from agentbot.browser.play import BrowserFactory
from agentbot.services.llm import OpenAIClient
from agentbot.services.page_analyzer import PageAnalyzer
from agentbot.utils.logging import get_logger

logger = get_logger("AIFormExample")


async def main():
    """Example: Analyze and fill a login form with AI."""
    
    # Step 1: Create LLM client
    llm = OpenAIClient(
        api_key="your-openai-api-key",  # Or use env var OPENAI_API_KEY
        model="gpt-4o-mini"
    )
    
    # Step 2: Create page analyzer (cache disabled for fresh analysis each time)
    analyzer = PageAnalyzer(llm, enable_cache=False)
    
    # Step 3: Create browser
    browser = BrowserFactory(
        headless=False,  # Set to True for headless
        user_data_root=Path(".user_data")
    )
    
    # Step 4: Navigate to page
    async with browser.page("demo-session") as page:
        logger.info("Navigating to login page...")
        await page.goto("https://visa.vfsglobal.com/tur/en/fra/login")
        await page.wait_for_load_state("networkidle")
        
        # Step 5: Get HTML and analyze with AI
        logger.info("Analyzing page with AI...")
        html = await page.content()
        analysis = await analyzer.analyze_page(html, page.url)
        
        # Step 6: Display what AI found
        logger.info(f"\n✨ AI Analysis Results:")
        logger.info(f"   Found {len(analysis.form_fields)} form fields")
        logger.info(f"   Found {len(analysis.action_sequence)} actions")
        
        for field in analysis.form_fields:
            logger.info(f"   - {field.purpose.value}: {field.selector}")
        
        # Step 7: Prepare your data
        session_data = {
            "credentials": {
                "username": "ruhsomurenzed@gmail.com",
                "password": "KOnya4242@@@"
            },
            "profile": {
                "first_name": "Mustafa Hüdai",
                "last_name": "Akgül"
            }
        }
        
        # Step 8: Fill form using AI's action sequence
        logger.info("\n🤖 Filling form with AI guidance...")
        for action in analysis.action_sequence:
            logger.info(f"   Action {action.order}: {action.description}")
            
            if action.action_type.value == "fill":
                # Get value from session data
                value = analyzer.get_value_from_session(
                    action.value_source or "",
                    session_data
                )
                if value:
                    await page.fill(action.selector, value)
                    logger.info(f"   ✓ Filled: {action.selector}")
            
            elif action.action_type.value == "click":
                await page.click(action.selector)
                logger.info(f"   ✓ Clicked: {action.selector}")
            
            # Wait if specified
            if action.wait_after:
                await asyncio.sleep(action.wait_after / 1000)
        
        logger.info("\n✅ Form filled successfully!")
        logger.info("Press Ctrl+C to exit...")
        await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

