"""Test interactive diagnostic module."""

import pytest
from pagescope.diagnostics.interactive import InteractiveTester
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
from pagescope.models.common import SessionConfig


@pytest.fixture
async def interactive_tester(mock_page, mock_cdp):
    """Create an InteractiveTester instance for testing."""
    from pagescope.models.common import SessionConfig
    from pagescope.diagnostics.interactive import InteractiveTester
    
    config = SessionConfig()
    tester = InteractiveTester(mock_page, mock_cdp, config)
    await tester.setup()
    return tester


@pytest.mark.asyncio
async def test_discover_interactive_elements(interactive_tester):
    """Test discovery of interactive elements."""
    # mock the page.evaluate method to return test data
    mock_elements = [
        {
            "type": "form",
            "selector": "form.login",
            "text": "Login Form",
            "action": "/login",
            "method": "POST",
            "fields": [
                {"type": "text", "name": "username", "required": True},
                {"type": "password", "name": "password", "required": True}
            ]
        },
        {
            "type": "button",
            "selector": "button.submit",
            "text": "Submit",
            "action": "click"
        }
    ]
    
    interactive_tester._page.evaluate.return_value = mock_elements
    
    elements = await interactive_tester._discover_interactive_elements()
    
    assert len(elements) == 2
    assert elements[0].type == "form"
    assert elements[0].selector == "form.login"
    assert elements[1].type == "button"
    assert elements[1].selector == "button.submit"


@pytest.mark.asyncio
async def test_generate_test_data(interactive_tester):
    """Test generation of realistic test data."""
    # test email field
    email_field = {"type": "email", "name": "email"}
    email_data = interactive_tester._generate_test_data(email_field)
    assert "@" in email_data
    assert ".com" in email_data
    
    # test password field
    password_field = {"type": "password", "name": "password"}
    password_data = interactive_tester._generate_test_data(password_field)
    assert len(password_data) > 0
    
    # test name field
    name_field = {"type": "text", "name": "username"}
    name_data = interactive_tester._generate_test_data(name_field)
    assert len(name_data) > 0
    
    # test default text field
    text_field = {"type": "text", "name": "message"}
    text_data = interactive_tester._generate_test_data(text_field)
    assert len(text_data) > 0


@pytest.mark.asyncio
async def test_log_interaction(interactive_tester):
    """Test interaction logging."""
    initial_count = len(interactive_tester._interaction_log)
    
    interactive_tester._log_interaction("click", "Clicked submit button")
    
    assert len(interactive_tester._interaction_log) == initial_count + 1
    event = interactive_tester._interaction_log[-1]
    assert event.action == "click"
    assert event.details == "Clicked submit button"
    assert event.timestamp > 0


@pytest.mark.asyncio
async def test_form_analysis(interactive_tester):
    """Test form analysis functionality."""
    # create test form element
    form_element = InteractiveElement(
        type="form",
        selector="form.test",
        text="Test Form",
        action="/submit",
        method="POST",
        fields=[
            {"name": "username", "type": "text", "required": True},
            {"name": "email", "type": "email", "required": True},
            {"name": "message", "type": "textarea", "required": False}
        ]
    )
    
    analysis = FormAnalysis(
        form_selector=form_element.selector,
        action=form_element.action,
        method=form_element.method,
        field_count=len(form_element.fields),
        required_fields=len([f for f in form_element.fields if f.get("required")]),
        fields=form_element.fields
    )
    
    assert analysis.form_selector == "form.test"
    assert analysis.action == "/submit"
    assert analysis.method == "POST"
    assert analysis.field_count == 3
    assert analysis.required_fields == 2


@pytest.mark.asyncio
async def test_interaction_log(interactive_tester):
    """Test interaction log functionality."""
    # add some test events
    interactive_tester._log_interaction("click", "Clicked button")
    interactive_tester._log_interaction("form_fill", "Filled username field")
    interactive_tester._log_interaction("error", "Failed to submit form")
    
    log = InteractionLog(
        total_interactions=len(interactive_tester._interaction_log),
        events=interactive_tester._interaction_log
    )
    
    assert log.total_interactions == 3
    assert len(log.events) == 3
    assert log.events[0].action == "click"
    assert log.events[1].action == "form_fill"
    assert log.events[2].action == "error"


@pytest.mark.asyncio
async def test_user_flow(interactive_tester):
    """Test user flow execution."""
    flow = UserFlow(
        name="Test Flow",
        description="Test user flow",
        steps=[
            {"action": "navigate", "target": "/login", "description": "Go to login page"},
            {"action": "fill", "target": "input.username", "description": "Fill username"},
            {"action": "click", "target": "button.submit", "description": "Click submit"},
            {"action": "wait", "duration": 2, "description": "Wait for response"}
        ]
    )
    
    result = UserFlowResult(
        flow_name=flow.name,
        steps_completed=3,
        total_steps=4,
        success=False,
        step_results=[
            {"step": "navigate", "success": True, "error": "", "url_after": "/login"},
            {"step": "fill", "success": True, "error": "", "url_after": "/login"},
            {"step": "click", "success": False, "error": "Button not found", "url_after": "/login"},
            {"step": "wait", "success": False, "error": "Flow stopped", "url_after": "/login"}
        ]
    )
    
    assert result.flow_name == "Test Flow"
    assert result.steps_completed == 3
    assert result.total_steps == 4
    assert result.success is False
    assert len(result.step_results) == 4


@pytest.mark.asyncio
async def test_interactive_report(interactive_tester):
    """Test interactive report generation."""
    # create test data
    elements = [
        InteractiveElement(type="form", selector="form.login", text="Login Form"),
        InteractiveElement(type="button", selector="button.submit", text="Submit")
    ]
    
    forms_analysis = [
        FormAnalysis(
            form_selector="form.login",
            action="/login",
            method="POST",
            field_count=2,
            required_fields=2,
            fields=[{"name": "username"}, {"name": "password"}]
        )
    ]
    
    tested_elements = [
        {
            "element": elements[0],
            "action": "form_test",
            "fill_success": True,
            "submission": FormSubmission(
                form_selector="form.login",
                submitted_url="/dashboard",
                page_title="Dashboard",
                error_messages=[],
                success=True
            )
        }
    ]
    
    interaction_log = InteractionLog(
        total_interactions=3,
        events=[
            InteractionEvent(action="form_fill", details="Filled username", timestamp=1234567890),
            InteractionEvent(action="form_fill", details="Filled password", timestamp=1234567891),
            InteractionEvent(action="click", details="Clicked submit", timestamp=1234567892)
        ]
    )
    
    summary = {
        "total_elements": 2,
        "forms_found": 1,
        "buttons_found": 1,
        "interactions_attempted": 3
    }
    
    report = InteractiveReport(
        discovered_elements=elements,
        forms_analysis=forms_analysis,
        tested_elements=tested_elements,
        interaction_log=interaction_log,
        summary=summary
    )
    
    assert len(report.discovered_elements) == 2
    assert len(report.forms_analysis) == 1
    assert len(report.tested_elements) == 1
    assert report.interaction_log.total_interactions == 3
    assert report.summary["total_elements"] == 2
    assert report.summary["forms_found"] == 1


@pytest.mark.asyncio
async def test_analyze_method(interactive_tester):
    """Test the main analyze method."""
    # mock the discovery method to return a coroutine
    mock_elements = [
        InteractiveElement(
            type="form",
            selector="form.test",
            text="Test Form",
            fields=[{"name": "username", "type": "text"}]
        ),
        InteractiveElement(
            type="button",
            selector="button.test",
            text="Test Button"
        )
    ]
    
    async def mock_discover():
        return mock_elements
    
    interactive_tester._discover_interactive_elements = mock_discover
    
    # mock the fill and click methods to return coroutines
    async def mock_fill_form(form, data):
        return True
    
    async def mock_click_element(element):
        return True
    
    async def mock_analyze_form_submission(form):
        return FormSubmission(
            form_selector="form.test",
            submitted_url="/success",
            page_title="Success",
            error_messages=[],
            success=True
        )
    
    interactive_tester._fill_form = mock_fill_form
    interactive_tester._click_element = mock_click_element
    interactive_tester._analyze_form_submission = mock_analyze_form_submission
    
    # mock the log
    interactive_tester._interaction_log = [
        InteractionEvent(action="form_fill", details="Filled form", timestamp=1234567890),
        InteractionEvent(action="click", details="Clicked button", timestamp=1234567891)
    ]
    
    report = await interactive_tester.analyze()
    
    assert isinstance(report, InteractiveReport)
    assert len(report.discovered_elements) == 2
    assert len(report.forms_analysis) == 1
    assert len(report.tested_elements) == 2  # Both elements should be tested
    assert report.interaction_log.total_interactions == 2
    assert "total_elements" in report.summary
    assert "forms_found" in report.summary
    assert "buttons_found" in report.summary
    assert "interactions_attempted" in report.summary


