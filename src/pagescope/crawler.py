"""Crawler -- BFS link-following diagnostics across multiple pages."""

from __future__ import annotations

import base64
import time
from collections import deque
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    Playwright,
    async_playwright,
)

from pagescope.models.common import Finding, SessionConfig, Severity
from pagescope.models.crawler import CrawlReport, PageResult
from pagescope.orchestrator import Orchestrator, Symptom
from pagescope.session import DiagnosticSession


class Crawler:
    """BFS crawler that runs diagnostics on each discovered page.

    Shares a single browser instance across all pages for efficiency.
    Each page gets its own context + CDP session for clean isolation.

    Usage::

        crawler = Crawler()
        report = await crawler.crawl(
            "https://example.com",
            max_depth=2,
            symptoms=[Symptom.GENERAL_HEALTH],
        )
    """

    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()

    async def crawl(
        self,
        start_url: str,
        max_depth: int = 1,
        symptoms: list[Symptom] | None = None,
        same_domain: bool = True,
        max_pages: int = 20,
        include_screenshots: bool = False,
        on_page_complete: callable | None = None,
    ) -> CrawlReport:
        """Crawl from start_url, following links up to max_depth.

        Args:
            start_url: The URL to start crawling from.
            max_depth: Maximum link-follow depth (0 = only start page).
            symptoms: Symptoms to investigate on each page.
            same_domain: Only follow links on the same domain.
            max_pages: Maximum number of pages to crawl.
            include_screenshots: Capture screenshot of each page.
            on_page_complete: Optional callback(page_result) for progress reporting.

        Returns:
            CrawlReport with per-page results and aggregate findings.
        """
        t0 = time.monotonic()
        start_parsed = urlparse(start_url)
        start_domain = start_parsed.netloc

        pw: Playwright = await async_playwright().start()
        browser: Browser = await pw.chromium.launch(
            headless=self.config.headless,
            args=self.config.browser_args or None,
        )

        try:
            queue: deque[tuple[str, int]] = deque([(start_url, 0)])
            visited: set[str] = set()
            page_results: list[PageResult] = []
            total_links = 0
            pages_skipped = 0

            while queue and len(page_results) < max_pages:
                url, depth = queue.popleft()
                normalized = self._normalize_url(url)

                if normalized in visited:
                    pages_skipped += 1
                    continue
                visited.add(normalized)

                # filter by domain
                if same_domain and urlparse(url).netloc != start_domain:
                    pages_skipped += 1
                    continue

                result = await self._diagnose_page(
                    browser=browser,
                    url=url,
                    depth=depth,
                    symptoms=symptoms,
                    include_screenshot=include_screenshots,
                    max_depth=max_depth,
                    start_domain=start_domain if same_domain else None,
                )

                page_results.append(result)
                total_links += result.links_found

                if on_page_complete:
                    on_page_complete(result)

                # enqueue discovered links if we haven't hit max depth
                if depth < max_depth and result.report:
                    for flow in result.report.flows:
                        pass  # links are extracted inside _diagnose_page
                    # links are stored as metadata on the result
                    for link in result._discovered_links:  # type: ignore[attr-defined]
                        link_normalized = self._normalize_url(link)
                        if link_normalized not in visited:
                            queue.append((link, depth + 1))

        finally:
            await browser.close()
            await pw.stop()

        # aggregate findings across all pages
        all_findings = self._aggregate_findings(page_results)
        recommendations = self._aggregate_recommendations(page_results)
        duration = (time.monotonic() - t0) * 1000

        return CrawlReport(
            start_url=start_url,
            max_depth=max_depth,
            pages_crawled=len(page_results),
            pages_skipped=pages_skipped,
            total_links_found=total_links,
            page_results=page_results,
            aggregate_findings=all_findings,
            recommendations=recommendations,
            crawl_duration_ms=round(duration, 2),
        )

    async def _diagnose_page(
        self,
        browser: Browser,
        url: str,
        depth: int,
        symptoms: list[Symptom] | None,
        include_screenshot: bool,
        max_depth: int,
        start_domain: str | None,
    ) -> PageResult:
        """Run diagnostics on a single page using a fresh context."""
        discovered_links: list[str] = []

        try:
            # fresh context per page -- clean isolation
            context = await browser.new_context(
                viewport=self.config.viewport,
                user_agent=self.config.user_agent,
            )
            page = await context.new_page()
            cdp = await context.new_cdp_session(page)

            try:
                session = DiagnosticSession.from_existing(
                    page=page, cdp=cdp, config=self.config
                )
                orchestrator = Orchestrator(session)
                report = await orchestrator.diagnose(url=url, symptoms=symptoms)

                if include_screenshot:
                    screenshot_bytes = await page.screenshot(full_page=True)
                    report.screenshot_base64 = base64.b64encode(
                        screenshot_bytes
                    ).decode()

                # extract links if we haven't hit max depth
                if depth < max_depth:
                    discovered_links = await self._extract_links(
                        page, url, start_domain
                    )

                result = PageResult(
                    url=url,
                    depth=depth,
                    report=report,
                    links_found=len(discovered_links),
                )

            finally:
                try:
                    await cdp.detach()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass

        except Exception as exc:
            from pagescope.models.report import DiagnosticReport

            result = PageResult(
                url=url,
                depth=depth,
                report=DiagnosticReport(url=url),
                links_found=0,
                error=str(exc),
            )

        # stash discovered links for the BFS queue (not serialized in model)
        result._discovered_links = discovered_links  # type: ignore[attr-defined]
        return result

    async def _extract_links(
        self,
        page,
        current_url: str,
        start_domain: str | None,
    ) -> list[str]:
        """Extract and filter <a href> links from the current page."""
        try:
            raw_links = await page.evaluate("""
                () => {
                    const anchors = document.querySelectorAll('a[href]');
                    return Array.from(anchors)
                        .map(a => a.href)
                        .filter(href => href.startsWith('http'));
                }
            """)
        except Exception:
            return []

        seen: set[str] = set()
        filtered: list[str] = []

        for link in raw_links:
            normalized = self._normalize_url(link)
            if normalized in seen:
                continue
            seen.add(normalized)

            parsed = urlparse(link)

            # skip non-HTTP
            if parsed.scheme not in ("http", "https"):
                continue

            # skip common non-page extensions
            path_lower = parsed.path.lower()
            skip_extensions = (
                ".pdf", ".zip", ".tar", ".gz", ".jpg", ".jpeg", ".png",
                ".gif", ".svg", ".ico", ".css", ".js", ".woff", ".woff2",
                ".ttf", ".eot", ".mp3", ".mp4", ".avi", ".mov",
            )
            if any(path_lower.endswith(ext) for ext in skip_extensions):
                continue

            # same-domain filter
            if start_domain and parsed.netloc != start_domain:
                continue

            filtered.append(link)

        return filtered

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize a URL for deduplication (strip fragment, trailing slash)."""
        parsed = urlparse(url)
        # remove fragment, normalize trailing slash
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
        # intentionally ignoring query params for dedup -- same path = same page

    def _aggregate_findings(self, results: list[PageResult]) -> list[Finding]:
        """Merge findings across all pages, noting which page each came from."""
        all_findings: list[Finding] = []

        for result in results:
            if result.error:
                all_findings.append(
                    Finding(
                        severity=Severity.ERROR,
                        category="crawl",
                        title=f"Failed to diagnose {result.url}",
                        description=result.error,
                    )
                )
                continue

            for finding in result.report.findings:
                # tag findings with their source page
                tagged = finding.model_copy()
                if "source_url" not in tagged.details:
                    tagged.details = {**tagged.details, "source_url": result.url}
                all_findings.append(tagged)

        # sort by severity
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.ERROR: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3,
        }
        all_findings.sort(key=lambda f: severity_order.get(f.severity, 99))
        return all_findings

    def _aggregate_recommendations(self, results: list[PageResult]) -> list[str]:
        """Deduplicate recommendations across all pages."""
        seen: set[str] = set()
        recs: list[str] = []
        for result in results:
            for rec in result.report.recommendations:
                if rec not in seen:
                    seen.add(rec)
                    recs.append(rec)
        return recs
