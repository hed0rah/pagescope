"""Pytest fixtures and configuration for Troubleshot tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from playwright.async_api import CDPSession, Page


@pytest.fixture
def mock_cdp():
    """Mock Playwright CDPSession object."""
    cdp = MagicMock(spec=CDPSession)
    cdp.send = AsyncMock()
    cdp.on = MagicMock()
    cdp.detach = AsyncMock()
    return cdp


@pytest.fixture
def mock_page(mock_cdp):
    """Mock Playwright Page object."""
    page = MagicMock(spec=Page)
    page.evaluate = AsyncMock()
    page.goto = AsyncMock()
    page.screenshot = AsyncMock()
    # mock context.new_cdp_session so SecurityChecker can create its own session
    context = MagicMock()
    context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    page.context = context
    return page


@pytest.fixture
def sample_security_report():
    """Sample SecurityReport for testing."""
    from pagescope.models.security import (
        SecurityReport, SecuritySummary, TLSInfo, 
        MixedContentIssue, CSPViolation, CookieIssue
    )
    
    return SecurityReport(
        tls_info=TLSInfo(
            protocol="TLS 1.3",
            cipher="AES_256_GCM",
            certificate_subject="example.com",
            certificate_issuer="Let's Encrypt"
        ),
        mixed_content=[
            MixedContentIssue(
                url="http://example.com/script.js",
                resource_type="Script",
                resolution_status="blocked"
            )
        ],
        csp_violations=[
            CSPViolation(
                blocked_url="http://evil.com/script.js",
                violated_directive="script-src",
                effective_directive="script-src"
            )
        ],
        cookie_issues=[
            CookieIssue(
                name="session_id",
                domain="example.com",
                issue="missing-secure"
            )
        ],
        insecure_forms=[
            {
                "action": "http://example.com/submit",
                "method": "POST",
                "has_password": True
            }
        ],
        summary=SecuritySummary(
            security_state="insecure",
            mixed_content_count=1,
            csp_violation_count=1,
            cookie_issue_count=1,
            insecure_form_count=1,
            has_valid_certificate=True,
            protocol_version="TLS 1.3"
        )
    )


@pytest.fixture
def sample_accessibility_report():
    """Sample AccessibilityReport for testing."""
    from pagescope.models.accessibility import (
        AccessibilityReport, AccessibilitySummary,
        ImageIssue, FormIssue, ContrastIssue, HeadingIssue, ARIAIssue
    )
    
    return AccessibilityReport(
        contrast_issues=[
            ContrastIssue(
                selector="p",
                text_sample="Sample text",
                foreground="rgb(100, 100, 100)",
                background="rgb(200, 200, 200)",
                contrast_ratio=3.2,
                required_ratio=4.5,
                font_size="16px",
                wcag_level="AA"
            )
        ],
        form_issues=[
            FormIssue(
                selector='input[type="text"]',
                element_type="input",
                issue="missing-label",
                input_type="text"
            )
        ],
        image_issues=[
            ImageIssue(
                selector='img[src="image.jpg"]',
                src="image.jpg",
                issue="missing-alt"
            )
        ],
        heading_issues=[
            HeadingIssue(
                issue="multiple-h1",
                details="Found 3 <h1> elements. Pages should have exactly one.",
                headings=[
                    {"tag": "h1", "text": "First H1"},
                    {"tag": "h1", "text": "Second H1"},
                    {"tag": "h1", "text": "Third H1"}
                ]
            )
        ],
        aria_issues=[
            ARIAIssue(
                selector='[role="button"]',
                issue="missing-keyboard",
                details='Element with role="button" has no tabindex or keyboard handler.'
            )
        ],
        summary=AccessibilitySummary(
            has_lang=True,
            has_title=True,
            has_viewport=True,
            has_skip_link=False,
            has_landmarks=True,
            total_images=5,
            images_without_alt=1,
            total_form_inputs=3,
            form_inputs_without_labels=1,
            contrast_issues=1,
            heading_issues=1,
            aria_issues=1,
            keyboard_traps=0
        )
    )


@pytest.fixture
def sample_dom_report():
    """Sample DOMReport for testing."""
    from pagescope.models.dom import (
        DOMReport, DOMSummary, DOMSizeMetrics,
        CSSCoverageReport, CSSCoverageEntry, LayoutIssue
    )
    
    return DOMReport(
        size_metrics=DOMSizeMetrics(
            total_nodes=1000,
            total_elements=800,
            max_depth=12,
            max_children=8,
            body_children=5
        ),
        css_coverage=CSSCoverageReport(
            entries=[
                CSSCoverageEntry(
                    url="styles.css",
                    total_bytes=1000,
                    used_bytes=750,
                    unused_pct=25.0
                )
            ],
            total_bytes=1000,
            used_bytes=750,
            unused_pct=25.0
        ),
        layout_issues=[
            LayoutIssue(
                issue_type="no-dimensions-on-media",
                selector='img[src="image.jpg"]',
                details="Image has no explicit width/height -- may cause layout shifts (CLS)."
            )
        ],
        summary=DOMSummary(
            node_count=1000,
            element_count=800,
            max_depth=12,
            has_doctype=True,
            has_charset=True,
            has_viewport=True,
            stylesheets_count=2,
            scripts_count=3,
            inline_styles_count=5,
            css_coverage=CSSCoverageReport(
                entries=[
                    CSSCoverageEntry(
                        url="styles.css",
                        total_bytes=1000,
                        used_bytes=750,
                        unused_pct=25.0
                    )
                ],
                total_bytes=1000,
                used_bytes=750,
                unused_pct=25.0
            )
        )
    )