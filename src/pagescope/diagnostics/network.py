"""Enhanced Network diagnostics with Chrome DevTools-like functionality."""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from playwright.async_api import BrowserContext, Page

from pagescope.models.network import NetworkReport, NetworkSummary
from pagescope.models.common import SessionConfig
from pagescope.models.websocket import WebSocketConnection, WebSocketFrame


@dataclass
class NetworkRequest:
    """Detailed network request information."""
    request_id: str
    url: str
    method: str
    resource_type: str
    start_time: float
    end_time: Optional[float] = None
    response_status: Optional[int] = None
    response_size: Optional[int] = None
    request_headers: Dict[str, str] = field(default_factory=dict)
    response_headers: Dict[str, str] = field(default_factory=dict)
    timing: Dict[str, float] = field(default_factory=dict)
    initiator: Dict = field(default_factory=dict)
    priority: Optional[str] = None
    from_cache: bool = False
    from_service_worker: bool = False
    from_prefetch_cache: bool = False
    # enhanced fields for Chrome DevTools-like detail
    request_body: Optional[str] = None
    response_body: Optional[str] = None
    remote_ip: Optional[str] = None
    remote_port: Optional[int] = None
    protocol: Optional[str] = None
    security_state: Optional[str] = None
    blocked_cookies: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)


@dataclass
class NetworkWaterfall:
    """Network waterfall analysis."""
    total_requests: int = 0
    total_size: int = 0
    total_time: float = 0.0
    concurrent_requests: List[Tuple[float, int]] = field(default_factory=list)
    request_breakdown: Dict[str, int] = field(default_factory=dict)
    status_codes: Dict[int, int] = field(default_factory=dict)
    timing_phases: Dict[str, float] = field(default_factory=dict)


class NetworkInspector:
    """Enhanced network inspector with Chrome DevTools-like functionality."""

    def __init__(self, page: Page, cdp, config: SessionConfig,
                 on_request_complete=None, on_ws_frame=None):
        self._page = page
        self._context = page.context
        self._config = config
        self._requests: Dict[str, NetworkRequest] = {}
        self._responses: Dict[str, Dict] = {}
        self._timing_data: Dict[str, float] = {}
        self._waterfall = NetworkWaterfall()
        self._on_request_complete = on_request_complete
        self._on_ws_frame = on_ws_frame
        self._ws_connections: Dict[str, WebSocketConnection] = {}
        
    async def setup(self) -> None:
        """Setup network monitoring with detailed timing."""
        # use a dedicated CDP session for network monitoring
        self._cdp = await self._context.new_cdp_session(self._page)
        await self._cdp.send("Network.enable")

        # enable performance domain for detailed timing
        await self._cdp.send("Performance.enable")

        # Set up request/response monitoring
        self._cdp.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._cdp.on("Network.responseReceived", self._on_response_received)
        self._cdp.on("Network.loadingFinished", self._on_loading_finished)
        self._cdp.on("Network.loadingFailed", self._on_loading_failed)

        # webSocket monitoring
        self._cdp.on("Network.webSocketCreated", self._on_ws_created)
        self._cdp.on("Network.webSocketFrameSent", self._on_ws_frame_sent)
        self._cdp.on("Network.webSocketFrameReceived", self._on_ws_frame_received)
        self._cdp.on("Network.webSocketClosed", self._on_ws_closed)

        # Set up performance monitoring
        self._cdp.on("Performance.metrics", self._on_performance_metrics)
        
    def _on_request_will_be_sent(self, params: Dict) -> None:
        """Handle request will be sent event."""
        request_id = params["requestId"]
        request_data = params["request"]

        # skip chrome internal requests
        url = request_data.get("url", "")
        if url.startswith(("chrome://", "chrome-extension://", "data:")):
            return

        self._requests[request_id] = NetworkRequest(
            request_id=request_id,
            url=request_data["url"],
            method=request_data["method"],
            resource_type=params.get("type", "Other"),
            start_time=params["wallTime"],
            request_headers=request_data.get("headers", {}),
            initiator=params.get("initiator", {}),
            priority=params.get("priority"),
        )
            
    def _on_response_received(self, params: Dict) -> None:
        """Handle response received event."""
        request_id = params["requestId"]
        response_data = params["response"]

        if request_id in self._requests:
            request = self._requests[request_id]
            request.response_status = response_data.get("status")
            request.response_headers = response_data.get("headers", {})
            request.from_cache = response_data.get("fromDiskCache", False)
            request.from_service_worker = response_data.get("fromServiceWorker", False)
            request.from_prefetch_cache = response_data.get("fromPrefetchCache", False)
            request.remote_ip = response_data.get("remoteIPAddress")
            request.remote_port = response_data.get("remotePort")
            request.protocol = response_data.get("protocol")
            request.security_state = response_data.get("securityState")

            # timing data lives on response.timing
            if "timing" in response_data:
                request.timing = response_data["timing"]
                
    def _on_loading_finished(self, params: Dict) -> None:
        """Handle loading finished event."""
        request_id = params["requestId"]
        if request_id in self._requests:
            request = self._requests[request_id]
            request.end_time = time.time()
            request.response_size = params.get("encodedDataLength", 0)
            # fetch response body async
            asyncio.create_task(self._fetch_response_body(request))

    async def _fetch_response_body(self, request: NetworkRequest) -> None:
        """Fetch the response body via CDP and then fire the callback."""
        try:
            result = await self._cdp.send(
                "Network.getResponseBody",
                {"requestId": request.request_id},
            )
            body = result.get("body", "")
            if result.get("base64Encoded"):
                request.response_body = f"[base64 encoded, {len(body)} chars]"
            else:
                # cap at 100KB to avoid memory issues
                request.response_body = body[:102400] if body else None
        except Exception:
            # Some requests (redirects, etc.) won't have a body
            pass
        if self._on_request_complete:
            self._on_request_complete(request)

    def _on_loading_failed(self, params: Dict) -> None:
        """Handle loading failed event."""
        request_id = params["requestId"]
        if request_id in self._requests:
            request = self._requests[request_id]
            request.end_time = time.time()
            request.response_status = 0  # Failed request
            if self._on_request_complete:
                self._on_request_complete(request)
            
    # ── WebSocket handlers ──

    def _on_ws_created(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        url = params.get("url", "")
        initiator = params.get("initiator", {})
        self._ws_connections[request_id] = WebSocketConnection(
            request_id=request_id,
            url=url,
            created_at=time.time(),
            initiator_url=initiator.get("url", ""),
        )

    def _on_ws_frame_sent(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        conn = self._ws_connections.get(request_id)
        if not conn:
            return
        response = params.get("response", {})
        payload = response.get("payloadData", "")
        frame = WebSocketFrame(
            request_id=request_id,
            timestamp=params.get("timestamp", time.time()),
            direction="sent",
            opcode=response.get("opcode", 1),
            payload_data=payload[:10240],  # Cap at 10KB
            payload_length=len(payload),
            mask=response.get("mask", False),
        )
        conn.frames.append(frame)
        if self._on_ws_frame:
            self._on_ws_frame(conn, frame)

    def _on_ws_frame_received(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        conn = self._ws_connections.get(request_id)
        if not conn:
            return
        response = params.get("response", {})
        payload = response.get("payloadData", "")
        frame = WebSocketFrame(
            request_id=request_id,
            timestamp=params.get("timestamp", time.time()),
            direction="received",
            opcode=response.get("opcode", 1),
            payload_data=payload[:10240],
            payload_length=len(payload),
            mask=response.get("mask", False),
        )
        conn.frames.append(frame)
        if self._on_ws_frame:
            self._on_ws_frame(conn, frame)

    def _on_ws_closed(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        conn = self._ws_connections.get(request_id)
        if conn:
            conn.status = "closed"
            conn.closed_at = time.time()

    def _on_performance_metrics(self, params: Dict) -> None:
        """Handle performance metrics event."""
        self._timing_data.update({metric["name"]: metric["value"] for metric in params["metrics"]})
        
    async def analyze(self) -> NetworkReport:
        """Analyze network performance with Chrome DevTools-like detail."""
        # wait for page load to complete
        await self._page.wait_for_load_state("networkidle", timeout=self._config.timeout_ms)
        
        # get final performance metrics (reuse existing CDP session)
        metrics_result = await self._cdp.send("Performance.getMetrics")
        
        # build waterfall analysis
        self._build_waterfall()
        
        # calculate detailed timing breakdown
        timing_breakdown = self._calculate_timing_breakdown()
        
        # identify performance bottlenecks
        bottlenecks = self._identify_bottlenecks()
        
        # generate recommendations
        recommendations = self._generate_recommendations()
        
        # convert data to proper format for Pydantic models
        slow_requests_formatted = []
        for req in self._get_slow_requests():
            slow_requests_formatted.append({
                "url": req["url"],
                "duration_ms": req["duration"],
                "resource_type": req["type"] if "type" in req else req.get("resource_type", "Unknown"),
                "timing": None
            })
            
        failed_requests_formatted = []
        for req in self._get_failed_requests():
            failed_requests_formatted.append({
                "url": req["url"],
                "status": req["status"],
                "failure": f"HTTP {req['status']}",
                "resource_type": req.get("resource_type", "Unknown")
            })
            
        bottlenecks_formatted = []
        for bottleneck in bottlenecks:
            bottlenecks_formatted.append({
                "type": bottleneck["type"],
                "severity": bottleneck["severity"],
                "description": bottleneck["description"],
                "details": str(bottleneck["details"])
            })

        # convert requests to proper format for TUI
        requests_formatted = []
        completed_requests = [r for r in self._requests.values() if r.end_time is not None]
        
        for request in completed_requests:
            # calculate timing breakdown
            timing_data = None
            if request.timing:
                timing_data = {
                    "dns_ms": request.timing.get("dnsEnd", 0) - request.timing.get("dnsStart", 0),
                    "connect_ms": request.timing.get("connectEnd", 0) - request.timing.get("connectStart", 0),
                    "ssl_ms": request.timing.get("sslEnd", 0) - request.timing.get("sslStart", 0),
                    "send_ms": request.timing.get("sendEnd", 0) - request.timing.get("sendStart", 0),
                    "wait_ms": request.timing.get("receiveHeadersEnd", 0) - request.timing.get("sendEnd", 0),
                    "receive_ms": ((request.end_time - request.start_time) * 1000 if request.end_time else 0) - request.timing.get("receiveHeadersEnd", 0),
                    "total_ms": (request.end_time - request.start_time) * 1000 if request.end_time else 0
                }
            
            requests_formatted.append({
                "url": request.url,
                "method": request.method,
                "status": request.response_status or 0,
                "status_text": "OK" if request.response_status and request.response_status < 400 else "Failed",
                "resource_type": request.resource_type,
                "protocol": request.protocol,
                "remote_ip": request.remote_ip,
                "security_state": request.security_state,
                "timing": timing_data,
                "encoded_data_length": request.response_size or 0,
                "decoded_body_length": request.response_size or 0,
                "request_headers": request.request_headers,
                "headers": request.response_headers,
                "failure": None if request.response_status and request.response_status < 400 else f"HTTP {request.response_status}"
            })

        return NetworkReport(
            requests=requests_formatted,
            summary=NetworkSummary(
                total_requests=self._waterfall.total_requests,
                total_transfer_bytes=self._waterfall.total_size,
                requests_by_type=self._waterfall.request_breakdown
            ),
            slow_requests=slow_requests_formatted,
            failed_requests=failed_requests_formatted,
            waterfall={
                "total_requests": self._waterfall.total_requests,
                "total_size": self._waterfall.total_size,
                "total_time": self._waterfall.total_time,
                "concurrent_requests": self._waterfall.concurrent_requests,
                "request_breakdown": self._waterfall.request_breakdown,
                "status_codes": self._waterfall.status_codes,
                "timing_phases": self._waterfall.timing_phases
            },
            timing_breakdown=timing_breakdown,
            bottlenecks=bottlenecks_formatted,
            recommendations=recommendations,
            cache_analysis=self._analyze_cache_usage(),
            connection_analysis=self._analyze_connections()
        )
        
    def _build_waterfall(self) -> None:
        """Build detailed waterfall analysis."""
        completed_requests = [r for r in self._requests.values() if r.end_time is not None]
        
        self._waterfall.total_requests = len(completed_requests)
        self._waterfall.total_size = sum(r.response_size or 0 for r in completed_requests)
        
        if completed_requests:
            start_times = [r.start_time for r in completed_requests]
            end_times = [r.end_time for r in completed_requests]
            self._waterfall.total_time = max(end_times) - min(start_times)
            
        # analyze request breakdown by type
        for request in completed_requests:
            resource_type = request.resource_type
            self._waterfall.request_breakdown[resource_type] = self._waterfall.request_breakdown.get(resource_type, 0) + 1
            
            # analyze status codes
            if request.response_status:
                self._waterfall.status_codes[request.response_status] = self._waterfall.status_codes.get(request.response_status, 0) + 1
                
    def _calculate_timing_breakdown(self) -> Dict[str, float]:
        """Calculate detailed timing breakdown similar to Chrome DevTools."""
        timing_breakdown = {
            "dns_lookup": 0.0,
            "initial_connection": 0.0,
            "ssl_negotiation": 0.0,
            "time_to_first_byte": 0.0,
            "content_download": 0.0,
            "total_request_time": 0.0
        }
        
        completed_requests = [r for r in self._requests.values() if r.end_time is not None]
        
        for request in completed_requests:
            timing = request.timing
            if not timing:
                continue
                
            # calculate timing phases
            dns = timing.get("dnsStart", 0) if timing.get("dnsEnd", 0) > timing.get("dnsStart", 0) else 0
            connection = timing.get("connectEnd", 0) - timing.get("connectStart", 0)
            ssl = timing.get("sslEnd", 0) - timing.get("sslStart", 0) if timing.get("sslEnd", 0) > timing.get("sslStart", 0) else 0
            ttfb = timing.get("receiveHeadersEnd", 0) - timing.get("sendEnd", 0)
            download = timing.get("receiveHeadersEnd", 0) - timing.get("sendEnd", 0)
            total = request.end_time - request.start_time if request.end_time else 0
            
            timing_breakdown["dns_lookup"] += dns
            timing_breakdown["initial_connection"] += connection
            timing_breakdown["ssl_negotiation"] += ssl
            timing_breakdown["time_to_first_byte"] += ttfb
            timing_breakdown["content_download"] += download
            timing_breakdown["total_request_time"] += total
            
        return timing_breakdown
        
    def _identify_bottlenecks(self) -> List[Dict[str, str]]:
        """Identify performance bottlenecks."""
        bottlenecks = []
        
        # analyze slow requests
        slow_requests = self._get_slow_requests()
        if slow_requests:
            bottlenecks.append({
                "type": "slow_requests",
                "severity": "high" if any(r["duration"] > 3000 for r in slow_requests) else "medium",
                "description": f"Found {len(slow_requests)} slow requests",
                "details": slow_requests[:5]  # Top 5 slowest
            })
            
        # analyze large requests
        large_requests = self._get_large_requests()
        if large_requests:
            bottlenecks.append({
                "type": "large_requests",
                "severity": "medium",
                "description": f"Found {len(large_requests)} large requests",
                "details": large_requests[:5]  # Top 5 largest
            })
            
        # analyze failed requests
        failed_requests = self._get_failed_requests()
        if failed_requests:
            bottlenecks.append({
                "type": "failed_requests",
                "severity": "high",
                "description": f"Found {len(failed_requests)} failed requests",
                "details": failed_requests
            })
            
        # analyze connection issues
        connection_issues = self._analyze_connections()
        if connection_issues.get("connection_errors"):
            bottlenecks.append({
                "type": "connection_issues",
                "severity": "high",
                "description": f"Found {len(connection_issues['connection_errors'])} connection issues",
                "details": connection_issues["connection_errors"]
            })
            
        return bottlenecks
        
    def _generate_recommendations(self) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        # analyze request patterns
        completed_requests = [r for r in self._requests.values() if r.end_time is not None]
        
        # check for too many requests
        if len(completed_requests) > 50:
            recommendations.append("Consider reducing the number of HTTP requests through bundling and combining resources")
            
        # check for large responses
        total_size = sum(r.response_size or 0 for r in completed_requests)
        if total_size > 5 * 1024 * 1024:  # > 5MB
            recommendations.append("Consider compressing large resources and implementing lazy loading")
            
        # check for slow requests
        slow_count = len([r for r in completed_requests if (r.end_time - r.start_time) > 1000])
        if slow_count > len(completed_requests) * 0.1:  # > 10% are slow
            recommendations.append("Optimize server response times and consider CDN usage")
            
        # check for cache usage
        cache_hits = sum(1 for r in completed_requests if r.from_cache)
        if cache_hits < len(completed_requests) * 0.5:  # < 50% cache hit rate
            recommendations.append("Improve cache strategy with appropriate cache headers")
            
        return recommendations
        
    def _get_slow_requests(self) -> List[Dict[str, str]]:
        """Get slow requests (> 1 second)."""
        slow_requests = []
        threshold = 1000  # 1 second in ms
        
        for request in self._requests.values():
            if request.end_time and (request.end_time - request.start_time) * 1000 > threshold:
                slow_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "duration": (request.end_time - request.start_time) * 1000,
                    "size": request.response_size,
                    "status": request.response_status
                })
                
        return sorted(slow_requests, key=lambda x: x["duration"], reverse=True)
        
    def _get_large_requests(self) -> List[Dict[str, str]]:
        """Get large requests (> 100KB)."""
        large_requests = []
        threshold = 100 * 1024  # 100KB
        
        for request in self._requests.values():
            if request.response_size and request.response_size > threshold:
                large_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "size": request.response_size,
                    "type": request.resource_type,
                    "duration": (request.end_time - request.start_time) * 1000 if request.end_time else 0
                })
                
        return sorted(large_requests, key=lambda x: x["size"], reverse=True)
        
    def _get_failed_requests(self) -> List[Dict[str, str]]:
        """Get failed requests."""
        failed_requests = []
        
        for request in self._requests.values():
            if request.response_status and request.response_status >= 400:
                failed_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "status": request.response_status,
                    "duration": (request.end_time - request.start_time) * 1000 if request.end_time else 0
                })
                
        return failed_requests
        
    def _analyze_cache_usage(self) -> Dict[str, str]:
        """Analyze cache usage patterns."""
        completed_requests = [r for r in self._requests.values() if r.end_time is not None]
        
        cache_hits = sum(1 for r in completed_requests if r.from_cache)
        service_worker_hits = sum(1 for r in completed_requests if r.from_service_worker)
        prefetch_hits = sum(1 for r in completed_requests if r.from_prefetch_cache)
        
        return {
            "total_requests": len(completed_requests),
            "cache_hits": cache_hits,
            "service_worker_hits": service_worker_hits,
            "prefetch_hits": prefetch_hits,
            "cache_hit_rate": cache_hits / len(completed_requests) if completed_requests else 0,
            "recommendations": self._get_cache_recommendations(cache_hits, len(completed_requests))
        }
        
    def _get_cache_recommendations(self, cache_hits: int, total_requests: int) -> List[str]:
        """Get cache optimization recommendations."""
        recommendations = []
        hit_rate = cache_hits / total_requests if total_requests > 0 else 0
        
        if hit_rate < 0.5:
            recommendations.append("Implement proper cache headers for static resources")
            recommendations.append("Consider using service workers for better caching")
            
        return recommendations
        
    def _analyze_connections(self) -> Dict[str, str]:
        """Analyze connection patterns and issues."""
        connection_errors = []
        
        # look for connection-related issues
        for request in self._requests.values():
            if request.response_status in [0, 502, 503, 504]:
                connection_errors.append({
                    "url": request.url,
                    "status": request.response_status,
                    "method": request.method
                })
                
        return {
            "connection_errors": connection_errors,
            "total_requests": len(self._requests),
            "error_rate": len(connection_errors) / len(self._requests) if self._requests else 0
        }