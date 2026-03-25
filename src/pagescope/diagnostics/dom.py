"""DOM diagnostic module -- DOM size, CSS coverage, layout issues."""

from __future__ import annotations

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.common import SessionConfig
from pagescope.models.dom import (
    CSSCoverageEntry,
    CSSCoverageReport,
    DOMEvent,
    DOMReport,
    DOMSizeMetrics,
    DOMSummary,
    LayoutIssue,
)


class DOMInspector(BaseDiagnostic[DOMReport, DOMEvent]):
    """Inspects DOM structure, CSS coverage, and layout issues.

    CDP domains used:
    - CSS (startRuleUsageTracking / stopRuleUsageTracking)
    - DOM (getDocument for tree metrics)
    - Runtime (evaluate for DOM analysis)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)
        self._css_tracking = False

    async def setup(self) -> None:
        if self._enabled:
            return
        await self._cdp.send("DOM.enable")
        try:
            await self._cdp.send("CSS.enable")
            await self._cdp.send("CSS.startRuleUsageTracking")
            self._css_tracking = True
        except Exception:
            pass
        self._enabled = True

    async def _get_dom_metrics(self) -> DOMSizeMetrics:
        """Measure DOM complexity via JS evaluation."""
        try:
            data = await self._page.evaluate("""
                () => {
                    const all = document.querySelectorAll('*');
                    let maxDepth = 0;
                    let maxChildren = 0;

                    function getDepth(el) {
                        let depth = 0;
                        let node = el;
                        while (node.parentElement) {
                            depth++;
                            node = node.parentElement;
                        }
                        return depth;
                    }

                    for (const el of all) {
                        const depth = getDepth(el);
                        if (depth > maxDepth) maxDepth = depth;
                        if (el.children.length > maxChildren) maxChildren = el.children.length;
                    }

                    let totalNodes = 0;
                    const walker = document.createTreeWalker(document, NodeFilter.SHOW_ALL);
                    while (walker.nextNode()) totalNodes++;

                    return {
                        total_nodes: totalNodes,
                        total_elements: all.length,
                        max_depth: maxDepth,
                        max_children: maxChildren,
                        body_children: document.body ? document.body.children.length : 0,
                    };
                }
            """)
            return DOMSizeMetrics(
                total_nodes=data.get("total_nodes", 0),
                total_elements=data.get("total_elements", 0),
                max_depth=data.get("max_depth", 0),
                max_children=data.get("max_children", 0),
                body_children=data.get("body_children", 0),
            )
        except Exception:
            return DOMSizeMetrics()

    async def _get_css_coverage(self) -> CSSCoverageReport:
        """Get CSS rule usage tracking results."""
        if not self._css_tracking:
            return CSSCoverageReport()

        try:
            result = await self._cdp.send("CSS.stopRuleUsageTracking")
            rules = result.get("ruleUsage", [])

            # group by stylesheet URL
            by_sheet: dict[str, dict] = {}
            for rule in rules:
                url = rule.get("styleSheetId", "inline")
                if url not in by_sheet:
                    by_sheet[url] = {"total": 0, "used": 0}
                size = rule.get("endOffset", 0) - rule.get("startOffset", 0)
                by_sheet[url]["total"] += size
                if rule.get("used", False):
                    by_sheet[url]["used"] += size

            entries = []
            total_all = 0
            used_all = 0
            for sheet_id, data in by_sheet.items():
                total_all += data["total"]
                used_all += data["used"]
                unused_pct = 0.0
                if data["total"] > 0:
                    unused_pct = round((1 - data["used"] / data["total"]) * 100, 1)
                entries.append(
                    CSSCoverageEntry(
                        url=sheet_id,
                        total_bytes=data["total"],
                        used_bytes=data["used"],
                        unused_pct=unused_pct,
                    )
                )

            overall_unused = 0.0
            if total_all > 0:
                overall_unused = round((1 - used_all / total_all) * 100, 1)

            return CSSCoverageReport(
                entries=entries,
                total_bytes=total_all,
                used_bytes=used_all,
                unused_pct=overall_unused,
            )
        except Exception:
            return CSSCoverageReport()

    async def _check_layout_issues(self) -> list[LayoutIssue]:
        """Detect common layout problems via JS inspection."""
        try:
            issues_data = await self._page.evaluate("""
                () => {
                    const issues = [];

                    // Check for images without explicit dimensions
                    const images = document.querySelectorAll('img');
                    for (const img of images) {
                        if (!img.getAttribute('width') && !img.getAttribute('height') &&
                            !img.style.width && !img.style.height) {
                            issues.push({
                                issue_type: 'no-dimensions-on-media',
                                selector: img.src ? `img[src="${img.src.substring(0,80)}"]` : 'img',
                                details: 'Image has no explicit width/height -- may cause layout shifts (CLS).',
                            });
                        }
                    }

                    // Check for horizontal overflow
                    const docWidth = document.documentElement.scrollWidth;
                    const viewWidth = document.documentElement.clientWidth;
                    if (docWidth > viewWidth + 5) {
                        issues.push({
                            issue_type: 'horizontal-overflow',
                            selector: 'document',
                            details: `Page has horizontal overflow: ${docWidth}px content vs ${viewWidth}px viewport.`,
                        });
                    }

                    // Check for very large DOM
                    const nodeCount = document.querySelectorAll('*').length;
                    if (nodeCount > 1500) {
                        issues.push({
                            issue_type: 'huge-dom',
                            selector: 'document',
                            details: `DOM has ${nodeCount} elements (recommended: <1500). Large DOMs slow parsing and rendering.`,
                        });
                    }

                    // Check for missing viewport meta tag
                    if (!document.querySelector('meta[name="viewport"]')) {
                        issues.push({
                            issue_type: 'no-viewport-meta',
                            selector: 'head',
                            details: 'Missing <meta name="viewport"> -- page will not render properly on mobile.',
                        });
                    }

                    // Check for inline styles (code smell, specificity issues)
                    const inlineStyled = document.querySelectorAll('[style]');
                    if (inlineStyled.length > 20) {
                        issues.push({
                            issue_type: 'excessive-inline-styles',
                            selector: 'document',
                            details: `${inlineStyled.length} elements with inline styles -- consider using CSS classes.`,
                        });
                    }

                    return issues;
                }
            """)
            return [LayoutIssue(**d) for d in (issues_data or [])]
        except Exception:
            return []

    async def _get_page_metadata(self) -> dict:
        """Get basic page metadata for the summary."""
        try:
            return await self._page.evaluate("""
                () => ({
                    has_doctype: document.doctype !== null,
                    has_charset: !!document.querySelector('meta[charset]'),
                    has_viewport: !!document.querySelector('meta[name="viewport"]'),
                    stylesheets_count: document.styleSheets.length,
                    scripts_count: document.scripts.length,
                    inline_styles_count: document.querySelectorAll('[style]').length,
                })
            """)
        except Exception:
            return {}

    async def analyze(self) -> DOMReport:
        if not self._enabled:
            await self.setup()

        size_metrics = await self._get_dom_metrics()
        css_coverage = await self._get_css_coverage()
        layout_issues = await self._check_layout_issues()
        meta = await self._get_page_metadata()

        summary = DOMSummary(
            node_count=size_metrics.total_nodes,
            element_count=size_metrics.total_elements,
            max_depth=size_metrics.max_depth,
            has_doctype=meta.get("has_doctype", False),
            has_charset=meta.get("has_charset", False),
            has_viewport=meta.get("has_viewport", False),
            stylesheets_count=meta.get("stylesheets_count", 0),
            scripts_count=meta.get("scripts_count", 0),
            inline_styles_count=meta.get("inline_styles_count", 0),
            css_coverage=css_coverage,
        )

        return DOMReport(
            size_metrics=size_metrics,
            css_coverage=css_coverage,
            layout_issues=layout_issues,
            summary=summary,
        )

    async def teardown(self) -> None:
        try:
            await self._cdp.send("CSS.disable")
        except Exception:
            pass
        try:
            await self._cdp.send("DOM.disable")
        except Exception:
            pass
        await super().teardown()
