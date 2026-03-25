"""Pydantic models for network diagnostic output."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class RequestTiming(BaseModel):
    """Detailed timing breakdown for a network request (milliseconds)."""

    dns_ms: float = 0
    connect_ms: float = 0
    ssl_ms: float = 0
    send_ms: float = 0
    wait_ms: float = 0  # TTFB
    receive_ms: float = 0
    total_ms: float = 0


class RequestRecord(BaseModel):
    """A single captured HTTP request/response pair."""

    url: str
    method: str = "GET"
    status: int = 0
    status_text: str = ""
    resource_type: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    request_headers: dict[str, str] = Field(default_factory=dict)
    timing: RequestTiming | None = None
    encoded_data_length: int | None = None
    decoded_body_length: int | None = None
    failure: str | None = None
    initiator_type: str | None = None
    protocol: str | None = None
    remote_ip: str | None = None
    security_state: str | None = None


class NetworkEvent(BaseModel):
    """A real-time network event for streaming."""

    type: str  # "response", "failed", "redirect"
    record: RequestRecord


class SlowRequest(BaseModel):
    url: str
    duration_ms: float
    resource_type: str
    timing: RequestTiming | None = None


class FailedRequest(BaseModel):
    url: str
    status: int
    failure: str | None = None
    resource_type: str = ""


class NetworkSummary(BaseModel):
    """Aggregate statistics for all network activity."""

    total_requests: int = 0
    failed_requests: int = 0
    total_transfer_bytes: int = 0
    total_decoded_bytes: int = 0
    requests_by_type: dict[str, int] = Field(default_factory=dict)
    median_response_ms: float | None = None
    p95_response_ms: float | None = None


class NetworkWaterfall(BaseModel):
    """Network waterfall analysis."""
    total_requests: int = 0
    total_size: int = 0
    total_time: float = 0.0
    concurrent_requests: list[tuple[float, int]] = Field(default_factory=list)
    request_breakdown: dict[str, int] = Field(default_factory=dict)
    status_codes: dict[int, int] = Field(default_factory=dict)
    timing_phases: dict[str, float] = Field(default_factory=dict)


class NetworkReport(BaseModel):
    """Complete network diagnostic report with Chrome DevTools-like detail."""

    requests: list[RequestRecord] = Field(default_factory=list)
    summary: NetworkSummary = Field(default_factory=NetworkSummary)
    slow_requests: list[SlowRequest] = Field(default_factory=list)
    failed_requests: list[FailedRequest] = Field(default_factory=list)
    waterfall: NetworkWaterfall = Field(default_factory=NetworkWaterfall)
    timing_breakdown: dict[str, float] = Field(default_factory=dict)
    bottlenecks: list[dict[str, str]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    cache_analysis: dict[str, Any] = Field(default_factory=dict)
    connection_analysis: dict[str, Any] = Field(default_factory=dict)
