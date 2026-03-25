"""Pydantic models for accessibility diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContrastIssue(BaseModel):
    """An element with insufficient color contrast."""

    selector: str = ""
    text_sample: str = ""
    foreground: str = ""
    background: str = ""
    contrast_ratio: float = 0
    required_ratio: float = 4.5  # WCAG AA for normal text
    font_size: str = ""
    wcag_level: str = "AA"


class FormIssue(BaseModel):
    """A form element with accessibility problems."""

    selector: str = ""
    element_type: str = ""  # input, select, textarea
    issue: str = ""  # "missing-label", "no-autocomplete", "missing-aria"
    input_type: str = ""  # text, email, password, etc.


class ImageIssue(BaseModel):
    """An image with accessibility problems."""

    selector: str = ""
    src: str = ""
    issue: str = ""  # "missing-alt", "empty-alt-on-informative", "decorative-no-role"


class HeadingIssue(BaseModel):
    """A heading hierarchy problem."""

    issue: str = ""  # "skipped-level", "multiple-h1", "no-h1"
    details: str = ""
    headings: list[dict[str, str]] = Field(default_factory=list)


class ARIAIssue(BaseModel):
    """An ARIA usage problem."""

    selector: str = ""
    issue: str = ""  # "missing-keyboard", "invalid-role", "hidden-focusable"
    details: str = ""


class AccessibilityEvent(BaseModel):
    """A real-time accessibility event."""

    type: str
    detail: str = ""


class AccessibilitySummary(BaseModel):
    """Aggregate accessibility assessment."""

    has_lang: bool = False
    has_title: bool = False
    has_viewport: bool = False
    has_skip_link: bool = False
    has_landmarks: bool = False
    total_images: int = 0
    images_without_alt: int = 0
    total_form_inputs: int = 0
    form_inputs_without_labels: int = 0
    contrast_issues: int = 0
    heading_issues: int = 0
    aria_issues: int = 0
    keyboard_traps: int = 0


class AccessibilityReport(BaseModel):
    """Complete accessibility diagnostic report."""

    contrast_issues: list[ContrastIssue] = Field(default_factory=list)
    form_issues: list[FormIssue] = Field(default_factory=list)
    image_issues: list[ImageIssue] = Field(default_factory=list)
    heading_issues: list[HeadingIssue] = Field(default_factory=list)
    aria_issues: list[ARIAIssue] = Field(default_factory=list)
    summary: AccessibilitySummary = Field(default_factory=AccessibilitySummary)
