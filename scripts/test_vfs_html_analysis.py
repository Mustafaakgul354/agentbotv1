#!/usr/bin/env python3
"""Test AI analysis on real VFS HTML structure."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbot.services.llm import OpenAIClient
from agentbot.services.page_analyzer import PageAnalyzer
from agentbot.utils.logging import get_logger
from agentbot.utils.env import get_env

logger = get_logger("TestVFSHTML")


async def main():
    """Test AI analysis on VFS HTML."""
    
    # Get API key
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set")
        return
    
    # Read test HTML
    html_path = Path(__file__).parent.parent / "test_vfs_html.html"
    if not html_path.exists():
        logger.error(f"Test HTML not found: {html_path}")
        return
    
    html_content = html_path.read_text(encoding="utf-8")
    logger.info(f"Loaded test HTML ({len(html_content)} chars)")
    
    # Create LLM and analyzer
    llm = OpenAIClient(api_key=api_key, model="gpt-4o-mini")
    analyzer = PageAnalyzer(llm, enable_cache=False)
    
    # Analyze
    logger.info("\n" + "="*80)
    logger.info("ANALYZING VFS LOGIN HTML WITH AI")
    logger.info("="*80)
    
    analysis = await analyzer.analyze_page(
        html_content, 
        "https://visa.vfsglobal.com/tur/tr/fra/login"
    )
    
    # Display results
    logger.info("\n" + "="*80)
    logger.info("ANALYSIS RESULTS")
    logger.info("="*80)
    
    logger.info(f"\n📊 Summary:")
    logger.info(f"   URL: {analysis.url}")
    logger.info(f"   Form Fields: {len(analysis.form_fields)}")
    logger.info(f"   Actions: {len(analysis.action_sequence)}")
    logger.info(f"   Has CAPTCHA: {analysis.has_captcha}")
    logger.info(f"   Has OTP: {analysis.has_otp}")
    
    if analysis.form_fields:
        logger.info(f"\n📝 IDENTIFIED FORM FIELDS:")
        for i, field in enumerate(analysis.form_fields, 1):
            logger.info(f"\n   {i}. {field.purpose.value.upper()}")
            logger.info(f"      Selector: {field.selector}")
            logger.info(f"      Type: {field.field_type}")
            logger.info(f"      Label: {field.label or 'N/A'}")
            logger.info(f"      Placeholder: {field.placeholder or 'N/A'}")
            logger.info(f"      Required: {field.required}")
            logger.info(f"      Confidence: {field.confidence:.2%}")
    
    if analysis.action_sequence:
        logger.info(f"\n🔄 ACTION SEQUENCE:")
        for action in analysis.action_sequence:
            logger.info(f"\n   {action.order}. {action.action_type.value.upper()}")
            logger.info(f"      Description: {action.description}")
            logger.info(f"      Selector: {action.selector}")
            if action.value_source:
                logger.info(f"      Value from: {action.value_source}")
            if action.wait_after:
                logger.info(f"      Wait after: {action.wait_after}ms")
    
    if analysis.submit_button:
        logger.info(f"\n✅ SUBMIT BUTTON:")
        logger.info(f"   Selector: {analysis.submit_button.selector}")
        logger.info(f"   Description: {analysis.submit_button.description}")
    
    # Expected vs Actual
    logger.info("\n" + "="*80)
    logger.info("VALIDATION")
    logger.info("="*80)
    
    expected_fields = {
        "email": "input#Email",
        "password": "input#Password",
    }
    
    for purpose, expected_selector in expected_fields.items():
        found = False
        for field in analysis.form_fields:
            if field.purpose.value == purpose:
                found = True
                if expected_selector in field.selector or field.selector in expected_selector:
                    logger.info(f"✅ {purpose.upper()}: Correct selector")
                else:
                    logger.warning(f"⚠️  {purpose.upper()}: Different selector")
                    logger.warning(f"   Expected: {expected_selector}")
                    logger.warning(f"   Got: {field.selector}")
                break
        
        if not found:
            logger.error(f"❌ {purpose.upper()}: Not detected!")
    
    # Check submit button
    if analysis.submit_button:
        if "submit" in analysis.submit_button.selector.lower() or "button" in analysis.submit_button.selector.lower():
            logger.info(f"✅ SUBMIT BUTTON: Detected")
        else:
            logger.warning(f"⚠️  SUBMIT BUTTON: Unusual selector: {analysis.submit_button.selector}")
    else:
        logger.error(f"❌ SUBMIT BUTTON: Not detected!")
    
    logger.info("\n" + "="*80)
    logger.info("TEST COMPLETE")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())

