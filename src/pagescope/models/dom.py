"""Pydantic models for DOM diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DOMSizeMetrics(BaseModel):
    """DOM complexity metrics."""

    total_nodes: int = 0
    total_elements: int = 0
    max_depth: int = 0
    max_children: int = 0
    body_children: int = 0


class CSSCoverageEntry(BaseModel):
    """CSS file coverage information."""

    url: str = ""
    total_bytes: int = 0
    used_bytes: int = 0
    unused_pct: float = 0


class CSSCoverageReport(BaseModel):
    """Aggregate CSS coverage."""

    entries: list[CSSCoverageEntry] = Field(default_factory=list)
    total_bytes: int = 0
    used_bytes: int = 0
    unused_pct: float = 0


class LayoutIssue(BaseModel):
    """A layout-related problem detected in the DOM."""

    issue_type: str = ""  # "overflow", "no-dimensions-on-media", "huge-dom"
    selector: str = ""
    details: str = ""


class DOMEvent(BaseModel):
    """A real-time DOM event."""

    type: str
    detail: str = ""


class DOMSummary(BaseModel):
    """Aggregate DOM assessment."""

    node_count: int = 0
    element_count: int = 0
    max_depth: int = 0
    has_doctype: bool = False
    has_charset: bool = False
    has_viewport: bool = False
    stylesheets_count: int = 0
    scripts_count: int = 0
    inline_styles_count: int = 0
    css_coverage: CSSCoverageReport = Field(default_factory=CSSCoverageReport)


class DOMReport(BaseModel):
    """Complete DOM diagnostic report."""

    size_metrics: DOMSizeMetrics = Field(default_factory=DOMSizeMetrics)
    css_coverage: CSSCoverageReport = Field(default_factory=CSSCoverageReport)
    layout_issues: list[LayoutIssue] = Field(default_factory=list)
    summary: DOMSummary = Field(default_factory=DOMSummary)
