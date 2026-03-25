"""Accessibility diagnostic module -- WCAG checks, contrast, forms, ARIA."""

from __future__ import annotations

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.accessibility import (
    AccessibilityEvent,
    AccessibilityReport,
    AccessibilitySummary,
    ARIAIssue,
    ContrastIssue,
    FormIssue,
    HeadingIssue,
    ImageIssue,
)
from pagescope.models.common import SessionConfig


class AccessibilityAuditor(BaseDiagnostic[AccessibilityReport, AccessibilityEvent]):
    """Audits page accessibility using DOM inspection and WCAG checks.

    Uses JavaScript evaluation to inspect the DOM for accessibility issues
    including missing alt text, form labels, heading hierarchy, contrast,
    ARIA misuse, and keyboard traps.

    CDP domains used:
    - Accessibility (getFullAXTree for accessibility tree)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)

    async def setup(self) -> None:
        if self._enabled:
            return
        try:
            await self._cdp.send("Accessibility.enable")
        except Exception:
            pass
        self._enabled = True

    async def _check_images(self) -> list[ImageIssue]:
        try:
            data = await self._page.evaluate("""
                () => {
                    const issues = [];
                    const images = document.querySelectorAll('img');
                    for (const img of images) {
                        const alt = img.getAttribute('alt');
                        if (alt === null) {
                            issues.push({
                                selector: img.src ? `img[src="${img.src.substring(0, 80)}"]` : 'img',
                                src: img.src || '',
                                issue: 'missing-alt',
                            });
                        }
                    }
                    return issues;
                }
            """)
            return [ImageIssue(**d) for d in (data or [])]
        except Exception:
            return []

    async def _check_forms(self) -> list[FormIssue]:
        try:
            data = await self._page.evaluate("""
                () => {
                    const issues = [];
                    const inputs = document.querySelectorAll('input, select, textarea');
                    for (const input of inputs) {
                        if (input.type === 'hidden' || input.type === 'submit' || input.type === 'button') continue;

                        const id = input.id;
                        const hasLabel = id && document.querySelector(`label[for="${id}"]`);
                        const hasAriaLabel = input.getAttribute('aria-label');
                        const hasAriaLabelledBy = input.getAttribute('aria-labelledby');
                        const hasTitle = input.getAttribute('title');
                        const parentLabel = input.closest('label');

                        if (!hasLabel && !hasAriaLabel && !hasAriaLabelledBy && !hasTitle && !parentLabel) {
                            let selector = input.tagName.toLowerCase();
                            if (input.type) selector += `[type="${input.type}"]`;
                            if (input.name) selector += `[name="${input.name}"]`;

                            issues.push({
                                selector: selector,
                                element_type: input.tagName.toLowerCase(),
                                issue: 'missing-label',
                                input_type: input.type || '',
                            });
                        }
                    }
                    return issues;
                }
            """)
            return [FormIssue(**d) for d in (data or [])]
        except Exception:
            return []

    async def _check_headings(self) -> list[HeadingIssue]:
        try:
            data = await self._page.evaluate("""
                () => {
                    const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')];
                    const issues = [];
                    const headingList = headings.map(h => ({
                        tag: h.tagName,
                        text: h.textContent.trim().substring(0, 60),
                    }));

                    // Check for multiple h1
                    const h1s = headings.filter(h => h.tagName === 'H1');
                    if (h1s.length > 1) {
                        issues.push({
                            issue: 'multiple-h1',
                            details: `Found ${h1s.length} <h1> elements. Pages should have exactly one.`,
                            headings: headingList,
                        });
                    }

                    // Check for no h1
                    if (h1s.length === 0 && headings.length > 0) {
                        issues.push({
                            issue: 'no-h1',
                            details: 'Page has headings but no <h1>. The first heading should be h1.',
                            headings: headingList,
                        });
                    }

                    // Check for skipped levels
                    let prevLevel = 0;
                    for (const h of headings) {
                        const level = parseInt(h.tagName[1]);
                        if (prevLevel > 0 && level > prevLevel + 1) {
                            issues.push({
                                issue: 'skipped-level',
                                details: `Heading level skipped from <h${prevLevel}> to <h${level}>. Expected <h${prevLevel + 1}>.`,
                                headings: headingList,
                            });
                            break;  // Only report once
                        }
                        prevLevel = level;
                    }

                    return issues;
                }
            """)
            return [HeadingIssue(**d) for d in (data or [])]
        except Exception:
            return []

    async def _check_contrast(self) -> list[ContrastIssue]:
        """Check text contrast using computed styles and relative luminance."""
        try:
            data = await self._page.evaluate("""
                () => {
                    function parseColor(str) {
                        const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (!m) return null;
                        return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
                    }

                    function luminance(r, g, b) {
                        const [rs, gs, bs] = [r, g, b].map(c => {
                            c = c / 255;
                            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
                        });
                        return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
                    }

                    function contrastRatio(l1, l2) {
                        const lighter = Math.max(l1, l2);
                        const darker = Math.min(l1, l2);
                        return (lighter + 0.05) / (darker + 0.05);
                    }

                    const issues = [];
                    const textElements = document.querySelectorAll('p, span, a, h1, h2, h3, h4, h5, h6, li, td, th, label, button, div');

                    for (const el of Array.from(textElements).slice(0, 50)) {
                        if (!el.textContent.trim()) continue;
                        const styles = getComputedStyle(el);
                        const fg = parseColor(styles.color);
                        const bg = parseColor(styles.backgroundColor);
                        if (!fg || !bg) continue;
                        // Skip transparent backgrounds
                        const bgAlpha = styles.backgroundColor.includes('rgba') ?
                            parseFloat(styles.backgroundColor.split(',')[3]) : 1;
                        if (bgAlpha < 0.1) continue;

                        const fgLum = luminance(...fg);
                        const bgLum = luminance(...bg);
                        const ratio = contrastRatio(fgLum, bgLum);

                        const fontSize = parseFloat(styles.fontSize);
                        const isBold = parseInt(styles.fontWeight) >= 700;
                        const isLarge = fontSize >= 18 || (fontSize >= 14 && isBold);
                        const required = isLarge ? 3.0 : 4.5;

                        if (ratio < required) {
                            let selector = el.tagName.toLowerCase();
                            if (el.className && typeof el.className === 'string') {
                                selector += '.' + el.className.split(' ')[0];
                            }
                            issues.push({
                                selector: selector,
                                text_sample: el.textContent.trim().substring(0, 40),
                                foreground: styles.color,
                                background: styles.backgroundColor,
                                contrast_ratio: Math.round(ratio * 100) / 100,
                                required_ratio: required,
                                font_size: styles.fontSize,
                                wcag_level: 'AA',
                            });
                        }
                    }
                    return issues;
                }
            """)
            return [ContrastIssue(**d) for d in (data or [])]
        except Exception:
            return []

    async def _check_aria(self) -> list[ARIAIssue]:
        try:
            data = await self._page.evaluate("""
                () => {
                    const issues = [];

                    // Interactive roles without keyboard handlers
                    const interactiveRoles = document.querySelectorAll('[role="button"], [role="link"], [role="checkbox"], [role="tab"]');
                    for (const el of interactiveRoles) {
                        if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'INPUT') continue;
                        const hasTabindex = el.hasAttribute('tabindex');
                        const hasKeyHandler = el.getAttribute('onkeydown') || el.getAttribute('onkeypress') || el.getAttribute('onkeyup');
                        if (!hasTabindex && !hasKeyHandler) {
                            issues.push({
                                selector: `[role="${el.getAttribute('role')}"]`,
                                issue: 'missing-keyboard',
                                details: `Element with role="${el.getAttribute('role')}" has no tabindex or keyboard handler.`,
                            });
                        }
                    }

                    // Focusable content hidden with aria-hidden
                    const hiddenContainers = document.querySelectorAll('[aria-hidden="true"]');
                    for (const container of hiddenContainers) {
                        const focusable = container.querySelectorAll('a, button, input, select, textarea, [tabindex]');
                        if (focusable.length > 0) {
                            issues.push({
                                selector: '[aria-hidden="true"]',
                                issue: 'hidden-focusable',
                                details: `aria-hidden="true" container has ${focusable.length} focusable element(s) -- they are hidden from screen readers but still tabbable.`,
                            });
                        }
                    }

                    return issues;
                }
            """)
            return [ARIAIssue(**d) for d in (data or [])]
        except Exception:
            return []

    async def _get_page_summary(self) -> dict:
        try:
            return await self._page.evaluate("""
                () => ({
                    has_lang: !!document.documentElement.lang,
                    has_title: !!document.title.trim(),
                    has_viewport: !!document.querySelector('meta[name="viewport"]'),
                    has_skip_link: !!document.querySelector('a[href="#main"], a[href="#content"], .skip-link, .skip-nav, [class*="skip"]'),
                    has_landmarks: !!(document.querySelector('header, [role="banner"]') &&
                                      document.querySelector('main, [role="main"]') &&
                                      document.querySelector('footer, [role="contentinfo"]')),
                    total_images: document.querySelectorAll('img').length,
                    total_form_inputs: document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').length,
                })
            """)
        except Exception:
            return {}

    async def analyze(self) -> AccessibilityReport:
        if not self._enabled:
            await self.setup()

        image_issues = await self._check_images()
        form_issues = await self._check_forms()
        heading_issues = await self._check_headings()
        contrast_issues = await self._check_contrast()
        aria_issues = await self._check_aria()
        page_meta = await self._get_page_summary()

        summary = AccessibilitySummary(
            has_lang=page_meta.get("has_lang", False),
            has_title=page_meta.get("has_title", False),
            has_viewport=page_meta.get("has_viewport", False),
            has_skip_link=page_meta.get("has_skip_link", False),
            has_landmarks=page_meta.get("has_landmarks", False),
            total_images=page_meta.get("total_images", 0),
            images_without_alt=len(image_issues),
            total_form_inputs=page_meta.get("total_form_inputs", 0),
            form_inputs_without_labels=len(form_issues),
            contrast_issues=len(contrast_issues),
            heading_issues=len(heading_issues),
            aria_issues=len(aria_issues),
        )

        return AccessibilityReport(
            contrast_issues=contrast_issues,
            form_issues=form_issues,
            image_issues=image_issues,
            heading_issues=heading_issues,
            aria_issues=aria_issues,
            summary=summary,
        )

    async def teardown(self) -> None:
        try:
            await self._cdp.send("Accessibility.disable")
        except Exception:
            pass
        await super().teardown()
