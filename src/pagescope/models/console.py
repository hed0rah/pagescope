"""Pydantic models for console diagnostic output."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ConsoleLevel(str, Enum):
    LOG = "log"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"
    VERBOSE = "verbose"


class ConsoleEntry(BaseModel):
    """A single console message."""

    level: ConsoleLevel
    text: str
    source: str = ""
    url: str = ""
    line_number: int | None = None
    column_number: int | None = None
    timestamp: float = 0


class ExceptionInfo(BaseModel):
    """An unhandled exception captured from the page."""

    message: str
    description: str = ""
    stack_trace: str = ""
    url: str = ""
    line_number: int | None = None
    column_number: int | None = None
    timestamp: float = 0


class Violation(BaseModel):
    """A browser violation (long task, blocked event, etc.)."""

    type: str
    description: str
    url: str = ""
    timestamp: float = 0


class ConsoleEvent(BaseModel):
    """A real-time console event for streaming."""

    type: str  # "message", "exception", "violation"
    entry: ConsoleEntry | None = None
    exception: ExceptionInfo | None = None
    violation: Violation | None = None


class ConsoleSummary(BaseModel):
    """Aggregate counts of console activity."""

    total_messages: int = 0
    errors: int = 0
    warnings: int = 0
    exceptions: int = 0
    violations: int = 0


class ConsoleReport(BaseModel):
    """Complete console diagnostic report."""

    entries: list[ConsoleEntry] = Field(default_factory=list)
    exceptions: list[ExceptionInfo] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    summary: ConsoleSummary = Field(default_factory=ConsoleSummary)
