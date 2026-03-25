"""Top-level diagnostic report model combining all module results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from pagescope.models.common import Finding


class DiagnosticFlow(BaseModel):
    """Result from running a single diagnostic module."""

    module: str
    report: Any | None = None
    status: str = "completed"  # "completed", "error", "skipped"
    error: str | None = None
    duration_ms: float | None = None


class DiagnosticReport(BaseModel):
    """Top-level diagnostic report combining all module results."""

    url: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    flows: list[DiagnosticFlow] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    screenshot_base64: str | None = None
