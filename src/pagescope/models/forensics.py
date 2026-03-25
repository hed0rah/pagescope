"""Pydantic models for forensics diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SecurityHeader(BaseModel):
    """A single security header assessment."""

    name: str
    present: bool = False
    value: str = ""
    grade: str = ""  # "good", "warning", "bad", "info"
    recommendation: str = ""


class SecurityHeadersReport(BaseModel):
    """Security headers scorecard."""

    headers: list[SecurityHeader] = Field(default_factory=list)
    score: int = 0  # 0-100
    grade: str = "F"  # A+ through F
    missing_critical: list[str] = Field(default_factory=list)


class HiddenElement(BaseModel):
    """A hidden DOM element."""

    tag: str = ""
    selector: str = ""
    reason: str = ""  # "display:none", "visibility:hidden", "opacity:0", etc.
    text_content: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    has_links: bool = False
    has_forms: bool = False
    has_inputs: bool = False


class PageComment(BaseModel):
    """An HTML comment extracted from the page."""

    text: str = ""
    location: str = ""  # "head", "body", "inline-script", etc.
    interesting: bool = False  # Flagged if contains keywords


class Endpoint(BaseModel):
    """A discovered URL/endpoint."""

    url: str
    source: str = ""  # "link", "form", "script", "ajax", "meta", "comment"
    method: str = "GET"
    context: str = ""  # Additional context (e.g., link text, form id)


class MetaTag(BaseModel):
    """A page meta tag."""

    name: str = ""
    property: str = ""
    content: str = ""
    http_equiv: str = ""


class ResponseBodyMatch(BaseModel):
    """A match found in a response body."""

    url: str
    content_type: str = ""
    match_text: str = ""
    line_number: int = 0
    context: str = ""  # Surrounding text


class ForensicsReport(BaseModel):
    """Complete forensics analysis report."""

    security_headers: SecurityHeadersReport = Field(
        default_factory=SecurityHeadersReport
    )
    hidden_elements: list[HiddenElement] = Field(default_factory=list)
    comments: list[PageComment] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    meta_tags: list[MetaTag] = Field(default_factory=list)
    interesting_findings: list[str] = Field(default_factory=list)
