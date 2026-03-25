"""Models for multi-page crawl results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from pagescope.models.common import Finding
from pagescope.models.report import DiagnosticReport


class PageResult(BaseModel):
    """Diagnostic result for a single crawled page."""

    url: str
    depth: int
    report: DiagnosticReport
    links_found: int = 0
    error: str | None = None


class CrawlConfig(BaseModel):
    """Configuration for a crawl operation."""

    max_depth: int = 1
    max_pages: int = 20
    same_domain: bool = True
    symptoms: list[str] | None = None
    include_screenshots: bool = False


class CrawlReport(BaseModel):
    """Aggregated diagnostic report across multiple crawled pages."""

    start_url: str
    max_depth: int
    pages_crawled: int = 0
    pages_skipped: int = 0
    total_links_found: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    page_results: list[PageResult] = Field(default_factory=list)
    aggregate_findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    crawl_duration_ms: float | None = None
