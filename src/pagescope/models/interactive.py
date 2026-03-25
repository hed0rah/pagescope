"""Pydantic models for interactive testing diagnostic output."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InteractiveElement(BaseModel):
    """An interactive element on a web page."""

    type: str = ""  # "form", "button", "a", "modal"
    selector: str = ""
    text: str = ""
    href: str = ""
    action: str = ""
    # form-specific fields
    fields: List[Dict[str, Any]] = Field(default_factory=list)
    method: str = ""
    action_url: str = ""


class FormAnalysis(BaseModel):
    """Analysis of a form's structure and requirements."""

    form_selector: str = ""
    action: str = ""
    method: str = ""
    field_count: int = 0
    required_fields: int = 0
    fields: List[Dict[str, Any]] = Field(default_factory=list)


class FormSubmission(BaseModel):
    """Result of submitting a form."""

    form_selector: str = ""
    submitted_url: str = ""
    page_title: str = ""
    error_messages: List[str] = Field(default_factory=list)
    success: bool = False


class InteractionEvent(BaseModel):
    """A single interaction event during testing."""

    action: str = ""  # "click", "form_fill", "form_submit", "error"
    details: str = ""
    timestamp: float = 0.0


class InteractionLog(BaseModel):
    """Log of all interaction events."""

    total_interactions: int = 0
    events: List[InteractionEvent] = Field(default_factory=list)


class UserFlowStep(BaseModel):
    """A single step in a user flow."""

    action: str = ""  # "navigate", "click", "fill_form", "wait"
    target: str = ""  # URL, selector, or other target
    description: str = ""
    duration: Optional[int] = None  # For wait actions


class UserFlow(BaseModel):
    """A defined user flow to test."""

    name: str = ""
    description: str = ""
    steps: List[UserFlowStep] = Field(default_factory=list)


class UserFlowResult(BaseModel):
    """Result of executing a user flow."""

    flow_name: str = ""
    steps_completed: int = 0
    total_steps: int = 0
    success: bool = False
    step_results: List[Dict[str, Any]] = Field(default_factory=list)


class InteractiveReport(BaseModel):
    """Complete interactive testing diagnostic report."""

    discovered_elements: List[InteractiveElement] = Field(default_factory=list)
    forms_analysis: List[FormAnalysis] = Field(default_factory=list)
    tested_elements: List[Dict[str, Any]] = Field(default_factory=list)
    interaction_log: InteractionLog = Field(default_factory=InteractionLog)
    summary: Dict[str, Any] = Field(default_factory=dict)