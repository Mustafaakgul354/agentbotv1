"""AI-powered page analyzer for intelligent form filling.

This module uses LLM to analyze HTML page structure and identify form fields,
their purposes, and the correct sequence for filling them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agentbot.services.llm import LLMClient
from agentbot.utils.logging import get_logger

logger = get_logger("PageAnalyzer")


class FieldPurpose(str, Enum):
    """Purpose/type of a form field."""
    EMAIL = "email"
    PASSWORD = "password"
    USERNAME = "username"
    PHONE = "phone"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    ADDRESS = "address"
    CITY = "city"
    COUNTRY = "country"
    POSTAL_CODE = "postal_code"
    DATE_OF_BIRTH = "date_of_birth"
    PASSPORT_NUMBER = "passport_number"
    OTP = "otp"
    CAPTCHA = "captcha"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SELECT = "select"
    TEXT = "text"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    """Type of action to perform."""
    FILL = "fill"
    CLICK = "click"
    SELECT = "select"
    WAIT = "wait"


@dataclass
class FormField:
    """Represents a form field identified in the page."""
    selector: str
    field_type: str  # input type: text, email, password, etc.
    purpose: FieldPurpose
    label: Optional[str] = None
    placeholder: Optional[str] = None
    required: bool = False
    confidence: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionStep:
    """Represents an action to perform."""
    action_type: ActionType
    selector: str
    description: str
    order: int
    value_source: Optional[str] = None  # e.g., "credentials.username"
    wait_after: int = 0  # milliseconds to wait after action


@dataclass
class PageAnalysis:
    """Complete analysis of a page."""
    url: str
    form_fields: List[FormField]
    action_sequence: List[ActionStep]
    submit_button: Optional[ActionStep] = None
    has_captcha: bool = False
    has_otp: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class PageAnalyzer:
    """AI-powered page analyzer for form detection and filling."""

    def __init__(self, llm: LLMClient, *, max_html_length: int = 50000, enable_cache: bool = False):
        self.llm = llm
        self.max_html_length = max_html_length
        self.enable_cache = enable_cache
        self._cache: Dict[str, PageAnalysis] = {}

    async def analyze_page(self, html: str, page_url: str) -> PageAnalysis:
        """Analyze a page and extract form information.
        
        Args:
            html: HTML content of the page
            page_url: URL of the page
            
        Returns:
            PageAnalysis with identified fields and action sequence
        """
        # 🔄 Cache kontrolü
        if self.enable_cache and page_url in self._cache:
            logger.info(f"📦 Using cached analysis for {page_url}")
            return self._cache[page_url]
        
        logger.info(f"🔍 Analyzing page: {page_url}")
        if not self.enable_cache:
            logger.info("   🔄 Fresh analysis (cache disabled)")
        
        # Extract form-related HTML
        form_html = self._extract_form_html(html)
        
        # Identify form fields
        fields = await self.identify_form_fields(form_html, page_url)
        
        # Identify action sequence
        actions = await self.identify_submit_sequence(form_html, fields, page_url)
        
        # Find submit button
        submit_button = next(
            (action for action in actions if action.action_type == ActionType.CLICK and "submit" in action.description.lower()),
            None
        )
        
        # Detect special fields
        has_captcha = any(f.purpose == FieldPurpose.CAPTCHA for f in fields)
        has_otp = any(f.purpose == FieldPurpose.OTP for f in fields)
        
        analysis = PageAnalysis(
            url=page_url,
            form_fields=fields,
            action_sequence=actions,
            submit_button=submit_button,
            has_captcha=has_captcha,
            has_otp=has_otp,
            metadata={
                "total_fields": len(fields),
                "total_actions": len(actions),
            }
        )
        
        # Store in cache if enabled
        if self.enable_cache:
            self._cache[page_url] = analysis
            logger.info(f"💾 Cached analysis for {page_url}")
        
        logger.info(f"✅ Analysis complete: {len(fields)} fields, {len(actions)} actions")
        return analysis

    def _extract_form_html(self, html: str) -> str:
        """Extract form-related HTML to reduce token usage.
        
        Extracts forms, inputs, buttons, labels, and related elements.
        """
        # Simple extraction: look for form elements and their context
        patterns = [
            r'<form[^>]*>.*?</form>',
            r'<input[^>]*>',
            r'<button[^>]*>.*?</button>',
            r'<label[^>]*>.*?</label>',
            r'<textarea[^>]*>.*?</textarea>',
            r'<select[^>]*>.*?</select>',
        ]
        
        # Try to extract forms first
        form_matches = re.findall(r'<form[^>]*>.*?</form>', html, re.DOTALL | re.IGNORECASE)
        
        if form_matches:
            # Use the first form (or concatenate if multiple)
            form_html = '\n'.join(form_matches[:3])  # Max 3 forms
        else:
            # No forms found, extract all form elements
            extracted = []
            for pattern in patterns:
                matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
                extracted.extend(matches[:20])  # Limit per pattern
            form_html = '\n'.join(extracted)
        
        # Truncate if too long
        if len(form_html) > self.max_html_length:
            form_html = form_html[:self.max_html_length] + "\n... (truncated)"
        
        return form_html if form_html else html[:self.max_html_length]

    async def identify_form_fields(self, html: str, page_url: str) -> List[FormField]:
        """Identify form fields in the HTML.
        
        Args:
            html: HTML content (preferably form-related)
            page_url: URL for context
            
        Returns:
            List of identified form fields
        """
        system_prompt = """You are an expert at analyzing HTML forms and identifying input fields.
Your task is to identify all form fields, their purposes, and create CSS/XPath selectors for them.

IMPORTANT NOTES:
- Look for Angular Material components (mat-form-field, matInput)
- Handle multilingual labels (English, Turkish, etc.)
- ID attributes are the most reliable selectors
- Consider aria-invalid, type, name, and placeholder attributes

Return a JSON array of form fields with this structure:
{
  "fields": [
    {
      "selector": "input#Email",
      "field_type": "email",
      "purpose": "email",
      "label": "E-posta",
      "placeholder": "jane.doe@email.com",
      "required": true,
      "confidence": 0.95
    }
  ]
}

Purpose values: email, password, username, phone, first_name, last_name, full_name, address, 
city, country, postal_code, date_of_birth, passport_number, otp, captcha, checkbox, radio, select, text, unknown

SELECTOR PRIORITY:
1. ID (e.g., input#Email, input#Password) - MOST RELIABLE
2. Type + ID (e.g., input[type="email"]#Email)
3. Type + attributes (e.g., input[type="email"][name="Email"])
4. XPath as last resort

LABEL DETECTION:
- Look for mat-label, label, aria-label
- Common email labels: "Email", "E-mail", "E-posta", "电子邮件"
- Common password labels: "Password", "Şifre", "密码", "Parola"

Set confidence to 0.95+ if you're very certain (has ID + correct type + clear label)."""

        user_prompt = f"""Analyze this HTML form and identify all input fields:

URL: {page_url}

HTML:
{html}

INSTRUCTIONS:
1. Find all input fields (look for <input>, matInput attributes)
2. Identify their purpose from id, name, type, label, placeholder
3. Create simple, reliable selectors (prefer input#ID format)
4. Set high confidence if you're certain

Example from this page:
- If you see: <input id="Email" type="email">
  Return: {{"selector": "input#Email", "purpose": "email", "confidence": 0.95}}
- If you see: <input id="Password" type="password">
  Return: {{"selector": "input#Password", "purpose": "password", "confidence": 0.95}}

Return JSON only, no markdown, no explanation."""

        try:
            response = await self.llm.generate(
                system=system_prompt,
                user=user_prompt,
                temperature=0.1
            )
            
            # Extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                # Remove markdown code blocks
                response = re.sub(r'^```(?:json)?\s*', '', response)
                response = re.sub(r'```\s*$', '', response)
            
            data = json.loads(response)
            
            fields = []
            for item in data.get("fields", []):
                try:
                    purpose_str = item.get("purpose", "unknown").lower()
                    # Map to enum
                    try:
                        purpose = FieldPurpose(purpose_str)
                    except ValueError:
                        purpose = FieldPurpose.UNKNOWN
                    
                    field_obj = FormField(
                        selector=item["selector"],
                        field_type=item.get("field_type", "text"),
                        purpose=purpose,
                        label=item.get("label"),
                        placeholder=item.get("placeholder"),
                        required=item.get("required", False),
                        confidence=item.get("confidence", 0.5),
                        attributes=item.get("attributes", {})
                    )
                    fields.append(field_obj)
                except Exception as e:
                    logger.warning(f"Failed to parse field: {e}, item: {item}")
                    continue
            
            logger.info(f"Identified {len(fields)} form fields")
            return fields
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response: {response}")
            return []
        except Exception as e:
            logger.error(f"Failed to identify form fields: {e}")
            return []

    async def identify_submit_sequence(
        self, 
        html: str, 
        fields: List[FormField],
        page_url: str
    ) -> List[ActionStep]:
        """Identify the sequence of actions to fill and submit the form.
        
        Args:
            html: HTML content
            fields: Previously identified form fields
            page_url: URL for context
            
        Returns:
            List of actions in the correct order
        """
        fields_summary = "\n".join([
            f"- {f.purpose.value}: {f.selector} (type: {f.field_type})"
            for f in fields
        ])
        
        system_prompt = """You are an expert at analyzing web forms and determining the correct sequence to fill them.

Your task is to create a step-by-step action sequence for filling a form.

IMPORTANT:
- Fill all required fields BEFORE clicking submit
- Add small waits (200-500ms) between field fills for human-like behavior
- Use simple, reliable selectors (prefer ID-based)
- For disabled buttons, still include the click action (browser will enable it after fields are filled)

Return a JSON array with this structure:
{
  "actions": [
    {
      "action_type": "fill",
      "selector": "input#Email",
      "description": "Fill email field",
      "order": 1,
      "value_source": "credentials.username",
      "wait_after": 300
    },
    {
      "action_type": "fill",
      "selector": "input#Password",
      "description": "Fill password field",
      "order": 2,
      "value_source": "credentials.password",
      "wait_after": 300
    },
    {
      "action_type": "click",
      "selector": "button[type='submit']",
      "description": "Click submit button",
      "order": 3,
      "value_source": null,
      "wait_after": 0
    }
  ]
}

action_type values: fill, click, select, wait
value_source: where to get the value (e.g., "credentials.username", "credentials.password", "profile.first_name")
order: sequence number (1, 2, 3, ...)
wait_after: milliseconds to wait after this action (100-1000ms, 0 for last action)"""

        user_prompt = f"""Create an action sequence for this form:

URL: {page_url}

Identified fields:
{fields_summary}

HTML:
{html[:10000]}

INSTRUCTIONS:
1. Create fill actions for each field in logical order
2. Map email/username fields to "credentials.username"
3. Map password fields to "credentials.password"
4. Add 200-500ms wait_after each fill (human-like)
5. Add click action for submit button at the end
6. Even if button is disabled="true", include the click (it will enable after fills)

Example sequence:
1. Fill email → credentials.username → wait 300ms
2. Fill password → credentials.password → wait 300ms  
3. Click submit button → wait 0ms

Return JSON only, no markdown, no explanation."""

        try:
            response = await self.llm.generate(
                system=system_prompt,
                user=user_prompt,
                temperature=0.1
            )
            
            # Extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```(?:json)?\s*', '', response)
                response = re.sub(r'```\s*$', '', response)
            
            data = json.loads(response)
            
            actions = []
            for item in data.get("actions", []):
                try:
                    action_type_str = item.get("action_type", "fill").lower()
                    try:
                        action_type = ActionType(action_type_str)
                    except ValueError:
                        action_type = ActionType.FILL
                    
                    action = ActionStep(
                        action_type=action_type,
                        selector=item["selector"],
                        description=item.get("description", ""),
                        order=item.get("order", 0),
                        value_source=item.get("value_source"),
                        wait_after=item.get("wait_after", 0)
                    )
                    actions.append(action)
                except Exception as e:
                    logger.warning(f"Failed to parse action: {e}, item: {item}")
                    continue
            
            # Sort by order
            actions.sort(key=lambda x: x.order)
            
            logger.info(f"Identified {len(actions)} actions in sequence")
            return actions
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response: {response}")
            return []
        except Exception as e:
            logger.error(f"Failed to identify action sequence: {e}")
            return []

    def get_value_from_session(self, value_source: str, session_data: Dict[str, Any]) -> Optional[str]:
        """Extract value from session data using dot notation.
        
        Args:
            value_source: Dot notation path (e.g., "credentials.username")
            session_data: Session data dictionary
            
        Returns:
            Value as string, or None if not found
        """
        if not value_source:
            return None
        
        parts = value_source.split(".")
        current = session_data
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            
            if current is None:
                return None
        
        return str(current) if current is not None else None


__all__ = [
    "PageAnalyzer",
    "PageAnalysis",
    "FormField",
    "ActionStep",
    "FieldPurpose",
    "ActionType",
]

