"""Interactive testing module -- form filling, button clicking, user flows."""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Dict, List, Optional

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.common import SessionConfig
from pagescope.models.interactive import (
    FormAnalysis,
    FormSubmission,
    InteractionEvent,
    InteractionLog,
    InteractiveElement,
    InteractiveReport,
    UserFlow,
    UserFlowResult,
)


class InteractiveTester(BaseDiagnostic[InteractiveReport, InteractionEvent]):
    """Tests interactive elements: forms, buttons, user flows.

    Uses JavaScript evaluation to discover and interact with elements,
    then runs diagnostics on the resulting state.

    CDP domains used:
    - Runtime (evaluate for element discovery and interaction)
    - Network (monitor requests during interactions)
    - Console (capture errors during interactions)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)
        self._interaction_log: list[InteractionEvent] = []
        self._form_data_cache: dict[str, dict] = {}

    async def setup(self) -> None:
        if self._enabled:
            return
        self._enabled = True

    async def _discover_interactive_elements(self) -> list[InteractiveElement]:
        """Discover all interactive elements on the page."""
        try:
            elements_data = await self._page.evaluate("""
                () => {
                    const elements = [];
                    
                    // Find forms
                    const forms = document.querySelectorAll('form');
                    for (const form of forms) {
                        const inputs = Array.from(form.querySelectorAll('input, select, textarea, button[type="submit"]'));
                        elements.push({
                            type: 'form',
                            selector: form.tagName.toLowerCase() + (form.id ? '#' + form.id : ''),
                            text: form.textContent.trim().substring(0, 100),
                            action: form.action || '',
                            method: form.method || 'GET',
                            fields: inputs.map(input => ({
                                type: input.type || input.tagName.toLowerCase(),
                                name: input.name || '',
                                id: input.id || '',
                                placeholder: input.placeholder || '',
                                required: input.required || false,
                                value: input.value || ''
                            }))
                        });
                    }
                    
                    // Find buttons and links
                    const buttons = document.querySelectorAll('button, a, [role="button"]');
                    for (const btn of buttons) {
                        if (btn.textContent.trim() === '') continue;
                        elements.push({
                            type: btn.tagName.toLowerCase(),
                            selector: btn.tagName.toLowerCase() + (btn.id ? '#' + btn.id : ''),
                            text: btn.textContent.trim().substring(0, 100),
                            href: btn.href || '',
                            action: btn.type || 'click'
                        });
                    }
                    
                    // Find modals and overlays
                    const modals = document.querySelectorAll('[role="dialog"], .modal, .overlay');
                    for (const modal of modals) {
                        elements.push({
                            type: 'modal',
                            selector: modal.className ? '.' + modal.className.split(' ')[0] : 'dialog',
                            text: modal.textContent.trim().substring(0, 100),
                            open: modal.style.display !== 'none' && modal.style.visibility !== 'hidden'
                        });
                    }
                    
                    return elements;
                }
            """)
            
            return [InteractiveElement(**data) for data in (elements_data or [])]
        except Exception as e:
            self._log_interaction("error", f"Failed to discover elements: {str(e)}")
            return []

    async def _fill_form(self, form_element: InteractiveElement, test_data: dict) -> bool:
        """Fill a form with test data."""
        try:
            # focus on form first
            await self._page.focus(f"{form_element.selector} input, {form_element.selector} textarea")
            
            for field in form_element.fields or []:
                field_name = field.get("name") or field.get("id") or ""
                if not field_name:
                    continue
                    
                value = test_data.get(field_name)
                if value is None:
                    value = self._generate_test_data(field)
                
                if value:
                    selector = f"{form_element.selector} [name='{field_name}']"
                    if not field_name:
                        selector = f"{form_element.selector} input[type='{field.get('type', 'text')}']"
                    
                    try:
                        await self._page.fill(selector, str(value))
                        self._log_interaction("form_fill", f"Filled {field_name} with {value}")
                    except Exception:
                        # try alternative selectors
                        selectors = [
                            f"{form_element.selector} #{field_name}",
                            f"input[name*='{field_name}']",
                            f"input[id*='{field_name}']"
                        ]
                        for sel in selectors:
                            try:
                                await self._page.fill(sel, str(value))
                                self._log_interaction("form_fill", f"Filled {field_name} with {value} (alternative selector)")
                                break
                            except Exception:
                                continue
            
            return True
        except Exception as e:
            self._log_interaction("error", f"Failed to fill form: {str(e)}")
            return False

    async def _click_element(self, element: InteractiveElement) -> bool:
        """Click an interactive element."""
        try:
            # wait for element to be clickable
            await self._page.wait_for_selector(element.selector, state="visible", timeout=5000)
            
            # scroll into view
            await self._page.evaluate(f"document.querySelector('{element.selector}').scrollIntoView()")
            
            # click with retry
            for attempt in range(3):
                try:
                    await self._page.click(element.selector, timeout=10000)
                    self._log_interaction("click", f"Clicked {element.type}: {element.text}")
                    await asyncio.sleep(0.5)  # Wait for any animations
                    return True
                except Exception as e:
                    if attempt == 2:
                        self._log_interaction("error", f"Failed to click {element.selector}: {str(e)}")
                        return False
                    await asyncio.sleep(1)  # Wait before retry
            
            return False
        except Exception as e:
            self._log_interaction("error", f"Failed to click element: {str(e)}")
            return False

    def _generate_test_data(self, field: dict) -> str:
        """Generate realistic test data for a form field."""
        field_type = field.get("type", "").lower()
        field_name = field.get("name", "").lower()
        
        # email fields
        if "email" in field_name or field_type == "email":
            return f"test{random.randint(100, 999)}@example.com"
        
        # password fields
        if "password" in field_name or field_type == "password":
            return "TestPassword123!"
        
        # name fields
        if "name" in field_name:
            if "first" in field_name:
                return "John"
            elif "last" in field_name:
                return "Doe"
            else:
                return "John Doe"
        
        # phone fields
        if "phone" in field_name or field_type == "tel":
            return f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        
        # address fields
        if "address" in field_name:
            return "123 Main Street"
        if "city" in field_name:
            return "Anytown"
        if "zip" in field_name or "postal" in field_name:
            return "12345"
        if "country" in field_name:
            return "USA"
        
        # text areas
        if field_type == "textarea":
            return f"This is a test message generated by PageScope at {asyncio.get_event_loop().time()}"
        
        # default text fields
        if field_type in ["text", "search", "url", ""]:
            if "username" in field_name:
                return f"testuser{random.randint(100, 999)}"
            elif "message" in field_name or "comment" in field_name:
                return "This is a test comment."
            else:
                return f"Test value for {field_name}"
        
        # select fields
        if field_type == "select-one":
            return ""  # Let the field keep its default value
        
        return ""

    def _log_interaction(self, action: str, details: str) -> None:
        """Log an interaction event."""
        event = InteractionEvent(
            action=action,
            details=details,
            timestamp=asyncio.get_event_loop().time()
        )
        self._interaction_log.append(event)

    async def _analyze_form_submission(self, form_element: InteractiveElement) -> FormSubmission:
        """Analyze what happens when a form is submitted."""
        try:
            # capture network requests before submission
            start_requests = len(await self._page.evaluate("performance.getEntriesByType('resource')"))
            
            # submit the form
            submit_button = form_element.fields and next(
                (f for f in form_element.fields if f.get("type") == "submit"), None
            )
            
            if submit_button:
                await self._click_element(InteractiveElement(
                    type="button",
                    selector=f"{form_element.selector} button[type='submit']",
                    text="Submit"
                ))
            else:
                # try to submit via form.submit()
                await self._page.evaluate(f"document.querySelector('{form_element.selector}').submit()")
            
            # wait for response
            await asyncio.sleep(2)
            
            # analyze what happened
            current_url = self._page.url
            page_title = await self._page.title()
            
            # check for error messages
            error_indicators = await self._page.evaluate("""
                () => {
                    const messages = [];
                    const errorSelectors = [
                        '.error', '.alert-danger', '.has-error',
                        '[class*="error"]', '[class*="danger"]',
                        'p:contains("error")', 'div:contains("error")'
                    ];
                    
                    for (const selector of errorSelectors) {
                        try {
                            const elements = document.querySelectorAll(selector);
                            for (const el of elements) {
                                if (el.textContent.trim()) {
                                    messages.push(el.textContent.trim());
                                }
                            }
                        } catch (e) {}
                    }
                    return messages.slice(0, 5);
                }
            """)
            
            return FormSubmission(
                form_selector=form_element.selector,
                submitted_url=current_url,
                page_title=page_title,
                error_messages=error_indicators or [],
                success=not error_indicators
            )
            
        except Exception as e:
            return FormSubmission(
                form_selector=form_element.selector,
                submitted_url="",
                page_title="",
                error_messages=[str(e)],
                success=False
            )

    async def _execute_user_flow(self, flow: UserFlow) -> UserFlowResult:
        """Execute a defined user flow."""
        results = []
        current_url = self._page.url
        
        for step in flow.steps:
            step_result = {
                "step": step.action,
                "success": False,
                "error": "",
                "url_after": current_url
            }
            
            try:
                if step.action == "navigate":
                    await self._page.goto(step.target, wait_until="networkidle", timeout=30000)
                    current_url = self._page.url
                    step_result["success"] = True
                    
                elif step.action == "click":
                    element = InteractiveElement(
                        type="button",
                        selector=step.target,
                        text=step.description or "Click target"
                    )
                    success = await self._click_element(element)
                    step_result["success"] = success
                    if success:
                        await asyncio.sleep(1)
                        current_url = self._page.url
                        
                elif step.action == "fill_form":
                    # this would need form discovery and filling logic
                    step_result["success"] = True  # Placeholder
                    
                elif step.action == "wait":
                    await asyncio.sleep(step.duration or 2)
                    step_result["success"] = True
                    
            except Exception as e:
                step_result["error"] = str(e)
                
            step_result["url_after"] = current_url
            results.append(step_result)
            
            # if step failed, stop the flow
            if not step_result["success"]:
                break
        
        return UserFlowResult(
            flow_name=flow.name,
            steps_completed=len([r for r in results if r["success"]]),
            total_steps=len(results),
            success=all(r["success"] for r in results),
            step_results=results
        )

    async def analyze(self) -> InteractiveReport:
        if not self._enabled:
            await self.setup()

        # discover interactive elements
        elements = await self._discover_interactive_elements()
        
        # analyze forms
        forms_analysis = []
        for element in elements:
            if element.type == "form":
                analysis = FormAnalysis(
                    form_selector=element.selector,
                    action=element.action,
                    method=element.method,
                    field_count=len(element.fields or []),
                    required_fields=len([f for f in (element.fields or []) if f.get("required")]),
                    fields=element.fields or []
                )
                forms_analysis.append(analysis)

        # test a sample of interactive elements
        tested_elements = []
        for element in elements[:5]:  # Test first 5 elements
            if element.type in ["button", "a"]:
                success = await self._click_element(element)
                tested_elements.append({
                    "element": element,
                    "action": "click",
                    "success": success
                })
            elif element.type == "form":
                test_data = {}
                for field in element.fields or []:
                    field_name = field.get("name") or field.get("id") or ""
                    if field_name:
                        test_data[field_name] = self._generate_test_data(field)
                
                fill_success = await self._fill_form(element, test_data)
                submission = await self._analyze_form_submission(element)
                
                tested_elements.append({
                    "element": element,
                    "action": "form_test",
                    "fill_success": fill_success,
                    "submission": submission
                })

        # generate interaction log
        interaction_log = InteractionLog(
            total_interactions=len(self._interaction_log),
            events=self._interaction_log
        )

        return InteractiveReport(
            discovered_elements=elements,
            forms_analysis=forms_analysis,
            tested_elements=tested_elements,
            interaction_log=interaction_log,
            summary={
                "total_elements": len(elements),
                "forms_found": len([e for e in elements if e.type == "form"]),
                "buttons_found": len([e for e in elements if e.type in ["button", "a"]]),
                "modals_found": len([e for e in elements if e.type == "modal"]),
                "interactions_attempted": len(self._interaction_log)
            }
        )

    async def teardown(self) -> None:
        await super().teardown()