"""Shared types used across all diagnostic modules."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class SessionConfig(BaseModel):
    """Configuration for a DiagnosticSession."""

    headless: bool = True
    viewport: dict[str, int] = Field(
        default_factory=lambda: {"width": 1280, "height": 720}
    )
    user_agent: str | None = None
    browser_args: list[str] = Field(default_factory=list)
    timeout_ms: int = 30_000
    module_timeout_ms: int = 30_000
    slow_request_threshold_ms: int = 1000
    navigation_wait_until: str = "load"


class TimingInfo(BaseModel):
    """Generic timing information in milliseconds."""

    start_ms: float = 0
    end_ms: float = 0
    duration_ms: float = 0


class Finding(BaseModel):
    """A single diagnostic finding."""

    severity: Severity
    category: str
    title: str
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None
