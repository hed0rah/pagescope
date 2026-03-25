"""Unit tests for SecurityChecker diagnostic module."""

import asyncio
import pytest
from unittest.mock import AsyncMock
from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.security import SecurityChecker
from pagescope.models.common import SessionConfig
from pagescope.models.security import SecurityReport, MixedContentIssue, CSPViolation


def _make_evaluate_mock(*, forms=None, url="https://example.com", protocol="https:"):
    """Create a page.evaluate mock that handles different JS expressions."""
    forms = forms or []

    async def _evaluate(expr, *args, **kwargs):
        expr_str = str(expr).strip()
        if "location.href" in expr_str:
            return url
        if "location.protocol" in expr_str:
            return protocol
        if "querySelectorAll" in expr_str or "form" in expr_str.lower():
            return forms
        if "performance.getEntriesByType" in expr_str:
            return {"protocol": "h2"}
        return None

    return AsyncMock(side_effect=_evaluate)


@pytest.mark.asyncio
async def test_security_checker_setup(mock_page: Page, mock_cdp: CDPSession):
    """Test SecurityChecker setup and teardown."""
    config = SessionConfig()
    checker = SecurityChecker(mock_page, mock_cdp, config)
    
    # mock CDP responses
    mock_cdp.send = AsyncMock(return_value={})
    mock_cdp.on = AsyncMock()
    
    await checker.setup()
    
    # verify CDP domains were enabled
    assert mock_cdp.send.call_count >= 2
    calls = [call.args[0] for call in mock_cdp.send.call_args_list]
    assert "Security.enable" in calls
    assert "Audits.enable" in calls
    
    await checker.teardown()
    
    # verify teardown disabled domains
    teardown_calls = [call.args[0] for call in mock_cdp.send.call_args_list if "disable" in call.args[0]]
    assert "Security.disable" in teardown_calls
    assert "Audits.disable" in teardown_calls


@pytest.mark.asyncio
async def test_security_checker_analyze(mock_page: Page, mock_cdp: CDPSession):
    """Test SecurityChecker analyze method."""
    config = SessionConfig()
    checker = SecurityChecker(mock_page, mock_cdp, config)

    # mock CDP responses
    mock_cdp.send = AsyncMock(side_effect=[
        {"visibleSecurityState": {"certificateSecurityState": {}}},
        {}
    ])
    mock_cdp.on = AsyncMock()
    mock_page.evaluate = _make_evaluate_mock()

    await checker.setup()
    report = await checker.analyze()

    assert isinstance(report, SecurityReport)
    assert report.summary is not None


@pytest.mark.asyncio
async def test_security_checker_mixed_content_detection(mock_page: Page, mock_cdp: CDPSession):
    """Test mixed content issue detection."""
    config = SessionConfig()
    checker = SecurityChecker(mock_page, mock_cdp, config)
    
    # mock mixed content issue
    mixed_content_issue = {
        "code": "MixedContentIssue",
        "details": {
            "mixedContentIssueDetails": {
                "insecureURL": "http://example.com/script.js",
                "resourceType": "Script",
                "resolutionStatus": "blocked"
            }
        }
    }
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"visibleSecurityState": {"certificateSecurityState": {}}},
        {}
    ])
    mock_cdp.on = AsyncMock()
    mock_page.evaluate = _make_evaluate_mock()

    await checker.setup()

    # directly add the issue to the internal list to test the functionality
    checker._mixed_content.append(
        MixedContentIssue(
            url="http://example.com/script.js",
            resource_type="Script",
            resolution_status="blocked"
        )
    )

    report = await checker.analyze()

    assert len(report.mixed_content) == 1
    assert report.mixed_content[0].url == "http://example.com/script.js"
    assert report.summary.mixed_content_count == 1


@pytest.mark.asyncio
async def test_security_checker_csp_violations(mock_page: Page, mock_cdp: CDPSession):
    """Test CSP violation detection."""
    config = SessionConfig()
    checker = SecurityChecker(mock_page, mock_cdp, config)
    
    # mock CSP violation
    csp_violation = {
        "code": "ContentSecurityPolicyIssue",
        "details": {
            "contentSecurityPolicyIssueDetails": {
                "blockedURL": "http://evil.com/script.js",
                "violatedDirective": "script-src",
                "effectiveDirective": "script-src",
                "sourceCodeLocation": {
                    "url": "https://example.com/page.html",
                    "lineNumber": 10,
                    "columnNumber": 5
                }
            }
        }
    }
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"visibleSecurityState": {"certificateSecurityState": {}}},
        {}
    ])
    mock_cdp.on = AsyncMock()
    mock_page.evaluate = _make_evaluate_mock()

    await checker.setup()

    # directly add the issue to the internal list to test the functionality
    checker._csp_violations.append(
        CSPViolation(
            blocked_url="http://evil.com/script.js",
            violated_directive="script-src",
            effective_directive="script-src"
        )
    )

    report = await checker.analyze()

    assert len(report.csp_violations) == 1
    assert report.csp_violations[0].blocked_url == "http://evil.com/script.js"
    assert report.csp_violations[0].violated_directive == "script-src"
    assert report.summary.csp_violation_count == 1


@pytest.mark.asyncio
async def test_security_checker_insecure_forms(mock_page: Page, mock_cdp: CDPSession):
    """Test insecure form detection."""
    config = SessionConfig()
    checker = SecurityChecker(mock_page, mock_cdp, config)
    
    # mock insecure forms
    insecure_forms = [
        {
            "action": "http://example.com/submit",
            "method": "POST",
            "has_password": True
        }
    ]
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"visibleSecurityState": {"certificateSecurityState": {}}},
        {}
    ])
    mock_cdp.on = AsyncMock()
    mock_page.evaluate = _make_evaluate_mock(
        forms=insecure_forms,
        url="http://example.com",
        protocol="http:",
    )

    await checker.setup()
    report = await checker.analyze()

    assert len(report.insecure_forms) == 1
    assert report.insecure_forms[0]["action"] == "http://example.com/submit"
    assert report.insecure_forms[0]["method"] == "POST"
    assert report.insecure_forms[0]["has_password"] == True
    assert report.summary.insecure_form_count == 1