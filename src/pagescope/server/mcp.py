"""FastMCP server exposing diagnostic tools for AI agents."""

from __future__ import annotations

import base64
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from pagescope.models.common import SessionConfig
from pagescope.orchestrator import Orchestrator, Symptom

mcp = FastMCP(
    name="pagescope",
    instructions=(
        "Web diagnostics toolkit. Use diagnose_url for general investigation, "
        "or individual check_* tools for targeted analysis. "
        "Start with check_console_errors if unsure -- console errors are the "
        "fastest signal for what's wrong."
    ),
)


@mcp.tool()
async def diagnose_url(
    url: Annotated[str, Field(description="The URL to diagnose")],
    symptoms: Annotated[
        list[str] | None,
        Field(
            description=(
                "Symptoms to investigate. Valid: slow_page, broken_layout, "
                "api_failures, console_errors, security_warnings, "
                "accessibility_issues, general_health. Defaults to general_health."
            ),
        ),
    ] = None,
    include_screenshot: Annotated[
        bool, Field(description="Include a base64 page screenshot")
    ] = False,
) -> dict:
    """Run a full diagnostic on a URL based on described symptoms.

    Primary entry point for AI agents. Describe what's wrong and the
    appropriate diagnostics run automatically. Returns findings ranked
    by severity with actionable recommendations.
    """
    from pagescope.session import DiagnosticSession

    parsed = None
    if symptoms:
        parsed = [Symptom(s) for s in symptoms]

    async with DiagnosticSession.start() as session:
        orchestrator = Orchestrator(session)
        report = await orchestrator.diagnose(url=url, symptoms=parsed)

        if include_screenshot:
            screenshot_bytes = await session.screenshot()
            report.screenshot_base64 = base64.b64encode(screenshot_bytes).decode()

    return report.model_dump(mode="json")


@mcp.tool()
async def check_network(
    url: Annotated[str, Field(description="The URL to analyze")],
    slow_threshold_ms: Annotated[
        int, Field(description="Requests slower than this (ms) are flagged")
    ] = 1000,
) -> dict:
    """Analyze all network requests made by a page.

    Captures every HTTP request/response, measures timing (DNS, connect,
    SSL, TTFB, download), identifies slow and failed requests. Use when
    investigating API failures, slow loading, or unexpected network behavior.
    """
    from pagescope.session import DiagnosticSession

    config = SessionConfig(slow_request_threshold_ms=slow_threshold_ms)
    async with DiagnosticSession.start(config=config) as session:
        await session.network.setup()
        await session.navigate(url)
        report = await session.network.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def check_performance(
    url: Annotated[str, Field(description="The URL to profile")],
    include_cpu_profile: Annotated[
        bool, Field(description="Run CPU profiling (adds ~5s)")
    ] = False,
) -> dict:
    """Profile page performance including Core Web Vitals.

    Measures LCP, FCP, CLS, TTFB and runtime metrics. Use when a page
    feels slow or unresponsive.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start() as session:
        session.performance._include_cpu_profile = include_cpu_profile
        await session.performance.setup()
        await session.navigate(url)
        report = await session.performance.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def check_console_errors(
    url: Annotated[str, Field(description="The URL to monitor")],
) -> dict:
    """Capture all console messages, errors, and unhandled exceptions.

    Monitors console output, unhandled promise rejections, thrown exceptions
    with stack traces. Use as a first diagnostic step for any misbehaving page.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start() as session:
        await session.console.setup()
        await session.navigate(url)
        report = await session.console.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def check_security(
    url: Annotated[str, Field(description="The URL to check")],
) -> dict:
    """Check page security: TLS, mixed content, CSP violations, cookies.

    Examines TLS connection, identifies mixed content, captures CSP violations,
    and checks for insecure forms. Use when you see security warnings or need
    to verify HTTPS configuration.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start() as session:
        await session.security.setup()
        await session.navigate(url)
        report = await session.security.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def check_accessibility(
    url: Annotated[str, Field(description="The URL to audit")],
) -> dict:
    """Audit page accessibility: contrast, forms, headings, images, ARIA.

    Checks color contrast (WCAG AA), form labels, heading hierarchy,
    image alt text, ARIA usage, and page landmarks. Use when verifying
    a page meets accessibility standards.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start() as session:
        await session.accessibility.setup()
        await session.navigate(url)
        report = await session.accessibility.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def check_dom(
    url: Annotated[str, Field(description="The URL to inspect")],
) -> dict:
    """Inspect DOM structure, CSS coverage, and layout issues.

    Measures DOM size and complexity, tracks CSS rule usage to find
    unused styles, and detects layout problems like missing viewport
    meta, horizontal overflow, and images without dimensions.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start() as session:
        await session.dom.setup()
        await session.navigate(url)
        report = await session.dom.analyze()
    return report.model_dump(mode="json")


@mcp.tool()
async def crawl_site(
    url: Annotated[str, Field(description="The starting URL to crawl from")],
    max_depth: Annotated[
        int, Field(description="Maximum link-follow depth (0=start page only, 1=start+linked pages, etc.)")
    ] = 1,
    max_pages: Annotated[
        int, Field(description="Maximum number of pages to crawl")
    ] = 10,
    symptoms: Annotated[
        list[str] | None,
        Field(
            description=(
                "Symptoms to investigate on each page. Valid: slow_page, broken_layout, "
                "api_failures, console_errors, security_warnings, "
                "accessibility_issues, general_health. Defaults to general_health."
            ),
        ),
    ] = None,
    same_domain: Annotated[
        bool, Field(description="Only follow links on the same domain")
    ] = True,
) -> dict:
    """Crawl a site following links and run diagnostics on each page.

    Performs BFS crawling from the start URL, following <a href> links up to
    max_depth levels deep. Runs the full diagnostic suite on each page
    and returns aggregate findings across the entire site. Useful for
    site-wide audits of performance, accessibility, or security.
    """
    from pagescope.crawler import Crawler
    from pagescope.orchestrator import Symptom as SymptomEnum

    parsed = [SymptomEnum(s) for s in symptoms] if symptoms else None

    crawler = Crawler()
    report = await crawler.crawl(
        start_url=url,
        max_depth=max_depth,
        symptoms=parsed,
        same_domain=same_domain,
        max_pages=max_pages,
    )
    return report.model_dump(mode="json")


@mcp.tool()
async def capture_screenshot(
    url: Annotated[str, Field(description="The URL to screenshot")],
    full_page: Annotated[
        bool, Field(description="Capture the full scrollable page")
    ] = True,
) -> dict:
    """Take a screenshot of a web page. Returns base64-encoded PNG."""
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        screenshot_bytes = await session.screenshot(full_page=full_page)
    return {
        "url": url,
        "format": "png",
        "base64": base64.b64encode(screenshot_bytes).decode(),
    }


@mcp.tool()
async def interact_with_page(
    url: Annotated[str, Field(description="The URL to interact with")],
    actions: Annotated[
        list[dict], Field(description="List of interaction actions to perform")
    ],
    wait_after_action: Annotated[
        float, Field(description="Seconds to wait after each action (default: 1.0)")
    ] = 1.0,
) -> dict:
    """Perform a sequence of interactions on a page.

    Actions can include:
    - {"type": "click", "selector": "button.submit", "description": "Click submit button"}
    - {"type": "fill", "selector": "input.email", "value": "test@example.com", "description": "Fill email field"}
    - {"type": "submit_form", "selector": "form.login", "description": "Submit login form"}
    - {"type": "wait", "duration": 2.0, "description": "Wait for 2 seconds"}

    Returns interaction results, any errors encountered, and page state after interactions.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        await session.interactive.setup()
        
        results = []
        for action in actions:
            action_type = action.get("type")
            description = action.get("description", "")
            
            try:
                if action_type == "click":
                    selector = action.get("selector", "")
                    element = {
                        "type": "button",
                        "selector": selector,
                        "text": description
                    }
                    success = await session.interactive._click_element(element)
                    results.append({
                        "action": action_type,
                        "description": description,
                        "success": success,
                        "selector": selector
                    })
                    
                elif action_type == "fill":
                    selector = action.get("selector", "")
                    value = action.get("value", "")
                    # create a mock form element for filling
                    form_element = {
                        "type": "form",
                        "selector": selector.split(" ")[0],  # Get form selector
                        "fields": [{"name": selector.split(" ")[-1].replace("[name='", "").replace("']", ""), "type": "text"}]
                    }
                    test_data = {form_element["fields"][0]["name"]: value}
                    success = await session.interactive._fill_form(form_element, test_data)
                    results.append({
                        "action": action_type,
                        "description": description,
                        "success": success,
                        "selector": selector,
                        "value": value
                    })
                    
                elif action_type == "submit_form":
                    selector = action.get("selector", "")
                    # find the form and submit it
                    form_element = {
                        "type": "form",
                        "selector": selector,
                        "fields": []
                    }
                    submission = await session.interactive._analyze_form_submission(form_element)
                    results.append({
                        "action": action_type,
                        "description": description,
                        "success": submission.success,
                        "selector": selector,
                        "submission_result": {
                            "submitted_url": submission.submitted_url,
                            "page_title": submission.page_title,
                            "error_messages": submission.error_messages
                        }
                    })
                    
                elif action_type == "wait":
                    duration = action.get("duration", wait_after_action)
                    import asyncio
                    await asyncio.sleep(duration)
                    results.append({
                        "action": action_type,
                        "description": description,
                        "duration": duration
                    })
                    
                else:
                    results.append({
                        "action": action_type,
                        "description": description,
                        "error": f"Unknown action type: {action_type}"
                    })
                    
                # wait after each action
                import asyncio
                await asyncio.sleep(wait_after_action)
                
            except Exception as e:
                results.append({
                    "action": action_type,
                    "description": description,
                    "error": str(e)
                })
        
        # analyze the final state
        report = await session.interactive.analyze()
        
    return {
        "url": url,
        "actions": actions,
        "results": results,
        "final_state": report.model_dump(mode="json")
    }


@mcp.tool()
async def test_user_flow(
    url: Annotated[str, Field(description="The URL to start the user flow from")],
    flow_definition: Annotated[
        dict, Field(description="User flow definition with steps")
    ],
) -> dict:
    """Execute a multi-step user flow and report results.

    Flow definition example:
    {
        "name": "Login Flow",
        "description": "Test user login process",
        "steps": [
            {"action": "navigate", "target": "/login", "description": "Go to login page"},
            {"action": "fill", "target": "input[name='username']", "value": "testuser", "description": "Fill username"},
            {"action": "fill", "target": "input[name='password']", "value": "password123", "description": "Fill password"},
            {"action": "click", "target": "button[type='submit']", "description": "Click login"},
            {"action": "wait", "duration": 3, "description": "Wait for redirect"}
        ]
    }

    Returns step-by-step results and overall flow success.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        await session.interactive.setup()
        
        flow_name = flow_definition.get("name", "User Flow")
        steps = flow_definition.get("steps", [])
        
        results = []
        current_url = session.page.url
        
        for step in steps:
            step_result = {
                "step": step.get("action", ""),
                "description": step.get("description", ""),
                "success": False,
                "error": "",
                "url_after": current_url
            }
            
            try:
                action = step.get("action", "")
                
                if action == "navigate":
                    target = step.get("target", "")
                    if target.startswith("/"):
                        target = url.rstrip("/") + target
                    await session.page.goto(target, wait_until="networkidle")
                    current_url = session.page.url
                    step_result["success"] = True
                    
                elif action == "click":
                    selector = step.get("target", "")
                    element = {
                        "type": "button",
                        "selector": selector,
                        "text": step.get("description", "")
                    }
                    success = await session.interactive._click_element(element)
                    step_result["success"] = success
                    if success:
                        await asyncio.sleep(1)
                        current_url = session.page.url
                        
                elif action == "fill":
                    selector = step.get("target", "")
                    value = step.get("value", "")
                    # create a mock form element for filling
                    form_element = {
                        "type": "form",
                        "selector": selector.split(" ")[0],
                        "fields": [{"name": selector.split(" ")[-1].replace("[name='", "").replace("']", ""), "type": "text"}]
                    }
                    test_data = {form_element["fields"][0]["name"]: value}
                    success = await session.interactive._fill_form(form_element, test_data)
                    step_result["success"] = success
                    
                elif action == "wait":
                    duration = step.get("duration", 2)
                    await asyncio.sleep(duration)
                    step_result["success"] = True
                    
                else:
                    step_result["error"] = f"Unknown action: {action}"
                    
            except Exception as e:
                step_result["error"] = str(e)
                
            step_result["url_after"] = current_url
            results.append(step_result)
            
            # if step failed, stop the flow
            if not step_result["success"]:
                break
        
        # analyze final state
        final_report = await session.interactive.analyze()
        
        flow_result = {
            "flow_name": flow_name,
            "steps_completed": len([r for r in results if r["success"]]),
            "total_steps": len(results),
            "success": all(r["success"] for r in results),
            "step_results": results,
            "final_state": final_report.model_dump(mode="json")
        }
        
    return {
        "url": url,
        "flow_definition": flow_definition,
        "flow_result": flow_result
    }


@mcp.tool()
async def analyze_interactive_elements(
    url: Annotated[str, Field(description="The URL to analyze")],
) -> dict:
    """Discover and analyze all interactive elements on a page.

    Returns comprehensive information about:
    - Forms (fields, actions, methods)
    - Buttons and links
    - Modals and overlays
    - Interactive elements that can be clicked or filled

    Use this tool to understand what interactions are possible on a page
    before running more targeted interaction tests.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        await session.interactive.setup()
        report = await session.interactive.analyze()
        
    return {
        "url": url,
        "interactive_elements": report.model_dump(mode="json")
    }


@mcp.tool()
async def test_form_submission(
    url: Annotated[str, Field(description="The URL containing the form")],
    form_selector: Annotated[
        str, Field(description="CSS selector for the form to test")
    ],
    test_data: Annotated[
        dict, Field(description="Test data to fill in the form fields")
    ],
) -> dict:
    """Test form submission with provided test data.

    Automatically fills the form with the provided test data and submits it,
    then analyzes the results including any error messages, redirects, or
    validation failures.

    Returns:
    - Form filling success
    - Submission success
    - Any error messages
    - Final page state
    - Redirect information
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        await session.interactive.setup()
        
        # create a mock form element
        form_element = {
            "type": "form",
            "selector": form_selector,
            "fields": [{"name": k, "type": "text"} for k in test_data.keys()]
        }
        
        # fill the form
        fill_success = await session.interactive._fill_form(form_element, test_data)
        
        # submit the form
        submission = await session.interactive._analyze_form_submission(form_element)
        
        # analyze final state
        final_report = await session.interactive.analyze()
        
    return {
        "url": url,
        "form_selector": form_selector,
        "test_data": test_data,
        "fill_success": fill_success,
        "submission": submission.model_dump(mode="json"),
        "final_state": final_report.model_dump(mode="json")
    }


@mcp.tool()
async def run_javascript(
    url: Annotated[str, Field(description="The URL to run JavaScript on")],
    expression: Annotated[
        str, Field(description="JavaScript expression to evaluate in page context")
    ],
) -> dict:
    """Execute JavaScript in the page context and return the result.

    Use for custom inspections not covered by built-in diagnostic tools.
    """
    from pagescope.session import DiagnosticSession

    async with DiagnosticSession.start(url=url) as session:
        result = await session.evaluate(expression)
    return {"url": url, "expression": expression, "result": result}


def run_server() -> None:
    """Start the MCP server (stdio transport)."""
    mcp.run()
