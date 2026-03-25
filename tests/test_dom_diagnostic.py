"""Unit tests for DOMInspector diagnostic module."""

import pytest
from unittest.mock import AsyncMock
from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.dom import DOMInspector
from pagescope.models.common import SessionConfig
from pagescope.models.dom import DOMReport


@pytest.mark.asyncio
async def test_dom_inspector_setup(mock_page: Page, mock_cdp: CDPSession):
    """Test DOMInspector setup and teardown."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock CDP responses
    mock_cdp.send = AsyncMock(return_value={})
    mock_cdp.on = AsyncMock()
    
    await inspector.setup()
    
    # verify CDP domains were enabled
    calls = [call.args[0] for call in mock_cdp.send.call_args_list]
    assert "DOM.enable" in calls
    assert "CSS.enable" in calls
    assert "CSS.startRuleUsageTracking" in calls
    
    await inspector.teardown()
    
    # verify teardown disabled domains
    teardown_calls = [call.args[0] for call in mock_cdp.send.call_args_list if "disable" in call.args[0]]
    assert "CSS.disable" in teardown_calls
    assert "DOM.disable" in teardown_calls


@pytest.mark.asyncio
async def test_dom_inspector_analyze(mock_page: Page, mock_cdp: CDPSession):
    """Test DOMInspector analyze method."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock CDP responses
    mock_cdp.send = AsyncMock(side_effect=[
        {"ruleUsage": []},  # CSS.stopRuleUsageTracking
        {}
    ])
    
    # mock the internal methods directly
    from pagescope.models.dom import DOMSizeMetrics, CSSCoverageReport
    
    inspector._get_dom_metrics = AsyncMock(return_value=DOMSizeMetrics(
        total_nodes=100,
        total_elements=80,
        max_depth=10,
        max_children=5,
        body_children=3
    ))
    
    inspector._get_page_metadata = AsyncMock(return_value={
        "has_doctype": True,
        "has_charset": True,
        "has_viewport": True,
        "stylesheets_count": 2,
        "scripts_count": 3,
        "inline_styles_count": 5
    })
    
    inspector._get_css_coverage = AsyncMock(return_value=CSSCoverageReport(
        entries=[],
        total_bytes=0,
        used_bytes=0,
        unused_pct=0
    ))
    
    inspector._check_layout_issues = AsyncMock(return_value=[])
    
    await inspector.setup()
    report = await inspector.analyze()
    
    assert isinstance(report, DOMReport)
    assert report.summary is not None
    assert report.summary.node_count == 100
    assert report.summary.element_count == 80
    assert report.summary.max_depth == 10
    assert report.summary.has_doctype == True
    assert report.summary.has_charset == True
    assert report.summary.has_viewport == True


@pytest.mark.asyncio
async def test_dom_inspector_css_coverage(mock_page: Page, mock_cdp: CDPSession):
    """Test CSS coverage analysis."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock CSS coverage data
    css_coverage_data = {
        "ruleUsage": [
            {
                "styleSheetId": "sheet1",
                "startOffset": 0,
                "endOffset": 100,
                "used": True
            },
            {
                "styleSheetId": "sheet1",
                "startOffset": 100,
                "endOffset": 200,
                "used": False
            },
            {
                "styleSheetId": "sheet2",
                "startOffset": 0,
                "endOffset": 50,
                "used": True
            }
        ]
    }
    
    mock_cdp.send = AsyncMock(return_value=css_coverage_data)
    
    # mock the internal methods to avoid complex setup
    from pagescope.models.dom import DOMSizeMetrics, CSSCoverageReport
    
    inspector._get_dom_metrics = AsyncMock(return_value=DOMSizeMetrics(
        total_nodes=100,
        total_elements=80,
        max_depth=10,
        max_children=5,
        body_children=3
    ))
    
    inspector._get_page_metadata = AsyncMock(return_value={
        "has_doctype": True,
        "has_charset": True,
        "has_viewport": True,
        "stylesheets_count": 2,
        "scripts_count": 3,
        "inline_styles_count": 5
    })
    
    inspector._check_layout_issues = AsyncMock(return_value=[])
    
    await inspector.setup()
    report = await inspector.analyze()
    
    assert report.css_coverage.total_bytes == 250  # 200 + 50
    assert report.css_coverage.used_bytes == 150  # 100 + 50
    assert report.css_coverage.unused_pct == 40.0  # 100/250 = 40%
    assert len(report.css_coverage.entries) == 2


@pytest.mark.asyncio
async def test_dom_inspector_layout_issues(mock_page: Page, mock_cdp: CDPSession):
    """Test layout issue detection."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock layout issues
    layout_issues = [
        {
            "issue_type": "no-dimensions-on-media",
            "selector": 'img[src="image.jpg"]',
            "details": "Image has no explicit width/height -- may cause layout shifts (CLS)."
        },
        {
            "issue_type": "huge-dom",
            "selector": "document",
            "details": "DOM has 2000 elements (recommended: <1500). Large DOMs slow parsing and rendering."
        }
    ]
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"ruleUsage": []},  # CSS.stopRuleUsageTracking
        {}
    ])
    
    mock_page.evaluate = AsyncMock(side_effect=[
        {
            "total_nodes": 2000,
            "total_elements": 1800,
            "max_depth": 15,
            "max_children": 10,
            "body_children": 8
        },  # DOM metrics
        layout_issues,  # layout issues
        {
            "has_doctype": True,
            "has_charset": True,
            "has_viewport": True,
            "stylesheets_count": 2,
            "scripts_count": 3,
            "inline_styles_count": 5
        }  # page metadata
    ])
    
    await inspector.setup()
    report = await inspector.analyze()
    
    assert len(report.layout_issues) == 2
    assert report.layout_issues[0].issue_type == "no-dimensions-on-media"
    assert report.layout_issues[1].issue_type == "huge-dom"
    assert "may cause layout shifts" in report.layout_issues[0].details
    assert "Large DOMs slow parsing" in report.layout_issues[1].details


@pytest.mark.asyncio
async def test_dom_inspector_missing_viewport(mock_page: Page, mock_cdp: CDPSession):
    """Test missing viewport meta tag detection."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock missing viewport
    layout_issues = [
        {
            "issue_type": "no-viewport-meta",
            "selector": "head",
            "details": "Missing <meta name=\"viewport\"> -- page will not render properly on mobile."
        }
    ]
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"ruleUsage": []},  # CSS.stopRuleUsageTracking
        {}
    ])
    
    mock_page.evaluate = AsyncMock(side_effect=[
        {
            "total_nodes": 100,
            "total_elements": 80,
            "max_depth": 10,
            "max_children": 5,
            "body_children": 3
        },  # DOM metrics
        layout_issues,  # layout issues
        {
            "has_doctype": True,
            "has_charset": True,
            "has_viewport": False,
            "stylesheets_count": 2,
            "scripts_count": 3,
            "inline_styles_count": 5
        }  # page metadata
    ])
    
    await inspector.setup()
    report = await inspector.analyze()
    
    assert len(report.layout_issues) == 1
    assert report.layout_issues[0].issue_type == "no-viewport-meta"
    assert report.summary.has_viewport == False


@pytest.mark.asyncio
async def test_dom_inspector_excessive_inline_styles(mock_page: Page, mock_cdp: CDPSession):
    """Test excessive inline styles detection."""
    config = SessionConfig()
    inspector = DOMInspector(mock_page, mock_cdp, config)
    
    # mock excessive inline styles
    layout_issues = [
        {
            "issue_type": "excessive-inline-styles",
            "selector": "document",
            "details": "50 elements with inline styles -- consider using CSS classes."
        }
    ]
    
    mock_cdp.send = AsyncMock(side_effect=[
        {"ruleUsage": []},  # CSS.stopRuleUsageTracking
        {}
    ])
    
    mock_page.evaluate = AsyncMock(side_effect=[
        {
            "total_nodes": 100,
            "total_elements": 80,
            "max_depth": 10,
            "max_children": 5,
            "body_children": 3
        },  # DOM metrics
        layout_issues,  # layout issues
        {
            "has_doctype": True,
            "has_charset": True,
            "has_viewport": True,
            "stylesheets_count": 2,
            "scripts_count": 3,
            "inline_styles_count": 50
        }  # page metadata
    ])
    
    await inspector.setup()
    report = await inspector.analyze()
    
    assert len(report.layout_issues) == 1
    assert report.layout_issues[0].issue_type == "excessive-inline-styles"
    assert "50 elements with inline styles" in report.layout_issues[0].details
    assert report.summary.inline_styles_count == 50