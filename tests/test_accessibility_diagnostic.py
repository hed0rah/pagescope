"""Unit tests for AccessibilityAuditor diagnostic module."""

import pytest
from unittest.mock import AsyncMock
from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.accessibility import AccessibilityAuditor
from pagescope.models.accessibility import AccessibilityReport
from pagescope.models.common import SessionConfig


@pytest.mark.asyncio
async def test_accessibility_auditor_setup(mock_page: Page, mock_cdp: CDPSession):
    """Test AccessibilityAuditor setup and teardown."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock CDP responses
    mock_cdp.send = AsyncMock(return_value={})
    mock_cdp.on = AsyncMock()
    
    await auditor.setup()
    
    # verify Accessibility domain was enabled
    calls = [call.args[0] for call in mock_cdp.send.call_args_list]
    assert "Accessibility.enable" in calls
    
    await auditor.teardown()
    
    # verify teardown disabled domain
    teardown_calls = [call.args[0] for call in mock_cdp.send.call_args_list if "disable" in call.args[0]]
    assert "Accessibility.disable" in teardown_calls


@pytest.mark.asyncio
async def test_accessibility_auditor_analyze(mock_page: Page, mock_cdp: CDPSession):
    """Test AccessibilityAuditor analyze method."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock page evaluation responses
    mock_page.evaluate = AsyncMock(side_effect=[
        [],  # images
        [],  # forms
        [],  # headings
        [],  # contrast
        [],  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert isinstance(report, AccessibilityReport)
    assert report.summary is not None
    assert report.summary.has_lang == True
    assert report.summary.has_title == True
    assert report.summary.has_viewport == True
    assert report.summary.has_skip_link == False
    assert report.summary.has_landmarks == True


@pytest.mark.asyncio
async def test_accessibility_auditor_image_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test image accessibility issue detection."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock images without alt text
    images_without_alt = [
        {
            "selector": 'img[src="image1.jpg"]',
            "src": "image1.jpg",
            "issue": "missing-alt"
        },
        {
            "selector": 'img[src="image2.jpg"]',
            "src": "image2.jpg",
            "issue": "missing-alt"
        }
    ]
    
    mock_page.evaluate = AsyncMock(side_effect=[
        images_without_alt,  # images
        [],  # forms
        [],  # headings
        [],  # contrast
        [],  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert len(report.image_issues) == 2
    assert report.image_issues[0].issue == "missing-alt"
    assert report.image_issues[1].issue == "missing-alt"
    assert report.summary.images_without_alt == 2


@pytest.mark.asyncio
async def test_accessibility_auditor_form_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test form accessibility issue detection."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock form inputs without labels
    form_issues = [
        {
            "selector": 'input[type="text"]',
            "element_type": "input",
            "issue": "missing-label",
            "input_type": "text"
        },
        {
            "selector": 'input[type="email"]',
            "element_type": "input",
            "issue": "missing-label",
            "input_type": "email"
        }
    ]
    
    mock_page.evaluate = AsyncMock(side_effect=[
        [],  # images
        form_issues,  # forms
        [],  # headings
        [],  # contrast
        [],  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert len(report.form_issues) == 2
    assert report.form_issues[0].issue == "missing-label"
    assert report.form_issues[1].issue == "missing-label"
    assert report.summary.form_inputs_without_labels == 2


@pytest.mark.asyncio
async def test_accessibility_auditor_contrast_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test contrast accessibility issue detection."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock contrast issues
    contrast_issues = [
        {
            "selector": "p",
            "text_sample": "Sample text",
            "foreground": "rgb(100, 100, 100)",
            "background": "rgb(200, 200, 200)",
            "contrast_ratio": 3.2,
            "required_ratio": 4.5,
            "font_size": "16px",
            "wcag_level": "AA"
        }
    ]
    
    mock_page.evaluate = AsyncMock(side_effect=[
        [],  # images
        [],  # forms
        [],  # headings
        contrast_issues,  # contrast
        [],  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert len(report.contrast_issues) == 1
    assert report.contrast_issues[0].contrast_ratio == 3.2
    assert report.contrast_issues[0].required_ratio == 4.5
    assert report.summary.contrast_issues == 1


@pytest.mark.asyncio
async def test_accessibility_auditor_heading_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test heading accessibility issue detection."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock heading issues
    heading_issues = [
        {
            "issue": "multiple-h1",
            "details": "Found 3 <h1> elements. Pages should have exactly one.",
            "headings": [
                {"tag": "h1", "text": "First H1"},
                {"tag": "h1", "text": "Second H1"},
                {"tag": "h1", "text": "Third H1"}
            ]
        }
    ]
    
    mock_page.evaluate = AsyncMock(side_effect=[
        [],  # images
        [],  # forms
        heading_issues,  # headings
        [],  # contrast
        [],  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert len(report.heading_issues) == 1
    assert report.heading_issues[0].issue == "multiple-h1"
    assert "Found 3 <h1> elements" in report.heading_issues[0].details
    assert report.summary.heading_issues == 1


@pytest.mark.asyncio
async def test_accessibility_auditor_aria_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test ARIA accessibility issue detection."""
    config = SessionConfig()
    auditor = AccessibilityAuditor(mock_page, mock_cdp, config)
    
    # mock ARIA issues
    aria_issues = [
        {
            "selector": '[role="button"]',
            "issue": "missing-keyboard",
            "details": 'Element with role="button" has no tabindex or keyboard handler.'
        }
    ]
    
    mock_page.evaluate = AsyncMock(side_effect=[
        [],  # images
        [],  # forms
        [],  # headings
        [],  # contrast
        aria_issues,  # aria
        {
            "has_lang": True,
            "has_title": True,
            "has_viewport": True,
            "has_skip_link": False,
            "has_landmarks": True,
            "total_images": 5,
            "total_form_inputs": 3,
        }
    ])
    
    await auditor.setup()
    report = await auditor.analyze()
    
    assert len(report.aria_issues) == 1
    assert report.aria_issues[0].issue == "missing-keyboard"
    assert report.summary.aria_issues == 1