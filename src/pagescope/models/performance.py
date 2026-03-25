"""Pydantic models for performance diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebVitals(BaseModel):
    """Core Web Vitals and related timing metrics."""

    lcp_ms: float | None = None
    fcp_ms: float | None = None
    cls: float | None = None
    inp_ms: float | None = None
    ttfb_ms: float | None = None
    total_blocking_time_ms: float | None = None
    dom_content_loaded_ms: float | None = None
    load_event_ms: float | None = None


class PerformanceMetric(BaseModel):
    """A single performance metric from the Performance CDP domain."""

    name: str
    value: float


class CpuProfile(BaseModel):
    """Summary of a CPU profiling session."""

    duration_ms: float = 0
    total_samples: int = 0
    top_functions: list[dict[str, object]] = Field(default_factory=list)


class PerformanceEvent(BaseModel):
    """A real-time performance event for streaming."""

    type: str
    metric: PerformanceMetric


class PerformanceReport(BaseModel):
    """Complete performance diagnostic report."""

    web_vitals: WebVitals = Field(default_factory=WebVitals)
    metrics: list[PerformanceMetric] = Field(default_factory=list)
    cpu_profile: CpuProfile | None = None
    resource_summary: dict[str, int] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
