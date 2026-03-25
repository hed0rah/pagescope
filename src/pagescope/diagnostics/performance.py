"""Performance diagnostic module -- Web Vitals, runtime metrics, CPU profiling."""

from __future__ import annotations

import asyncio

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.common import SessionConfig
from pagescope.models.performance import (
    CpuProfile,
    PerformanceEvent,
    PerformanceMetric,
    PerformanceReport,
    WebVitals,
)

# javaScript snippet to extract Web Vitals via the Navigation Timing API
# and PerformanceObserver (works without the web-vitals library).
_WEB_VITALS_JS = """
() => {
    const result = {};
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) {
        result.ttfb_ms = nav.responseStart - nav.requestStart;
        result.fcp_ms = null;
        result.dom_content_loaded_ms = nav.domContentLoadedEventEnd - nav.startTime;
        result.load_event_ms = nav.loadEventEnd - nav.startTime;
    }

    // FCP from paint entries
    const paints = performance.getEntriesByType('paint');
    for (const p of paints) {
        if (p.name === 'first-contentful-paint') {
            result.fcp_ms = p.startTime;
        }
    }

    // LCP from PerformanceObserver (best effort -- may not be available
    // if page loaded before observer was set up)
    const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
    if (lcpEntries.length > 0) {
        result.lcp_ms = lcpEntries[lcpEntries.length - 1].startTime;
    }

    // CLS from layout shift entries
    const layoutShifts = performance.getEntriesByType('layout-shift');
    let cls = 0;
    for (const ls of layoutShifts) {
        if (!ls.hadRecentInput) {
            cls += ls.value;
        }
    }
    result.cls = cls;

    return result;
}
"""

# javaScript snippet to set up PerformanceObservers early for LCP/CLS.
_SETUP_OBSERVERS_JS = """
() => {
    window.__pagescope_lcp = 0;
    window.__pagescope_cls = 0;

    try {
        new PerformanceObserver((list) => {
            const entries = list.getEntries();
            if (entries.length > 0) {
                window.__pagescope_lcp = entries[entries.length - 1].startTime;
            }
        }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch(e) {}

    try {
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                if (!entry.hadRecentInput) {
                    window.__pagescope_cls += entry.value;
                }
            }
        }).observe({ type: 'layout-shift', buffered: true });
    } catch(e) {}
}
"""

_READ_OBSERVERS_JS = """
() => ({
    lcp_ms: window.__pagescope_lcp || null,
    cls: window.__pagescope_cls || 0,
})
"""


class PerformanceProfiler(BaseDiagnostic[PerformanceReport, PerformanceEvent]):
    """Profiles page performance including Core Web Vitals and runtime metrics.

    CDP domains used:
    - Performance (getMetrics)
    - Profiler (CPU profiling)
    - Runtime (evaluate for Navigation Timing API)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)
        self._include_cpu_profile = False

    async def setup(self) -> None:
        if self._enabled:
            return
        await self._cdp.send("Performance.enable")
        self._enabled = True

        # inject PerformanceObservers via addInitScript so they run before
        # any page JS on every navigation (including the initial one).
        # the `buffered: true` option picks up entries from before the observer.
        script = _SETUP_OBSERVERS_JS.strip()
        # addInitScript expects a raw script body, not a function expression.
        # wrap the IIFE call so it auto-executes:
        await self._page.add_init_script(f"({script})()")

    async def get_web_vitals(self) -> WebVitals:
        """Extract Web Vitals from the page using Navigation Timing API."""
        # brief pause to let PerformanceObserver callbacks fire
        await asyncio.sleep(0.5)

        try:
            data = await self._page.evaluate(_WEB_VITALS_JS)
        except Exception:
            data = {}

        # merge with observer data if available
        try:
            observer_data = await self._page.evaluate(_READ_OBSERVERS_JS)
            if observer_data.get("lcp_ms") is not None and data.get("lcp_ms") is None:
                data["lcp_ms"] = observer_data["lcp_ms"]
            if observer_data.get("cls") is not None and data.get("cls") is None:
                data["cls"] = observer_data["cls"]
        except Exception:
            pass

        return WebVitals(
            lcp_ms=_round_or_none(data.get("lcp_ms")),
            fcp_ms=_round_or_none(data.get("fcp_ms")),
            cls=_round_or_none(data.get("cls"), 4),
            ttfb_ms=_round_or_none(data.get("ttfb_ms")),
            dom_content_loaded_ms=_round_or_none(data.get("dom_content_loaded_ms")),
            load_event_ms=_round_or_none(data.get("load_event_ms")),
        )

    async def get_metrics(self) -> list[PerformanceMetric]:
        """Get current Performance domain metrics."""
        result = await self._cdp.send("Performance.getMetrics")
        return [
            PerformanceMetric(name=m["name"], value=m["value"])
            for m in result.get("metrics", [])
        ]

    async def profile_cpu(self, duration_seconds: float = 5.0) -> CpuProfile:
        """Run a CPU profile for the specified duration."""
        await self._cdp.send("Profiler.enable")
        await self._cdp.send("Profiler.start")

        await asyncio.sleep(duration_seconds)

        result = await self._cdp.send("Profiler.stop")
        await self._cdp.send("Profiler.disable")

        profile = result.get("profile", {})
        nodes = profile.get("nodes", [])
        samples = profile.get("samples", [])

        # count samples per function
        node_map = {n["id"]: n for n in nodes}
        sample_counts: dict[int, int] = {}
        for s in samples:
            sample_counts[s] = sample_counts.get(s, 0) + 1

        # top functions by sample count
        top = sorted(sample_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_functions = []
        for node_id, count in top:
            node = node_map.get(node_id, {})
            call_frame = node.get("callFrame", {})
            top_functions.append({
                "function": call_frame.get("functionName", "(anonymous)"),
                "url": call_frame.get("url", ""),
                "line": call_frame.get("lineNumber", 0),
                "samples": count,
                "pct": round(count / len(samples) * 100, 1) if samples else 0,
            })

        duration_ms = (profile.get("endTime", 0) - profile.get("startTime", 0)) / 1000

        return CpuProfile(
            duration_ms=round(duration_ms, 2),
            total_samples=len(samples),
            top_functions=top_functions,
        )

    def _generate_recommendations(self, vitals: WebVitals) -> list[str]:
        """Generate actionable recommendations based on Web Vitals."""
        recs = []
        if vitals.lcp_ms is not None and vitals.lcp_ms > 2500:
            recs.append(
                f"LCP is {vitals.lcp_ms:.0f}ms (target: <2500ms). "
                "Check the largest visible element -- optimize images, "
                "preload critical resources, or reduce server response time."
            )
        if vitals.fcp_ms is not None and vitals.fcp_ms > 1800:
            recs.append(
                f"FCP is {vitals.fcp_ms:.0f}ms (target: <1800ms). "
                "Reduce render-blocking CSS/JS, inline critical styles, "
                "or use font-display: swap."
            )
        if vitals.cls is not None and vitals.cls > 0.1:
            recs.append(
                f"CLS is {vitals.cls:.3f} (target: <0.1). "
                "Add explicit width/height to images and embeds, "
                "avoid dynamically injected content above the fold."
            )
        if vitals.ttfb_ms is not None and vitals.ttfb_ms > 800:
            recs.append(
                f"TTFB is {vitals.ttfb_ms:.0f}ms (target: <800ms). "
                "Server response is slow -- check backend performance, "
                "enable caching, or use a CDN."
            )
        if vitals.total_blocking_time_ms is not None and vitals.total_blocking_time_ms > 200:
            recs.append(
                f"TBT is {vitals.total_blocking_time_ms:.0f}ms (target: <200ms). "
                "Main thread is blocked by long tasks -- break up large scripts, "
                "defer non-critical JS, or use web workers."
            )
        return recs

    async def analyze(self) -> PerformanceReport:
        if not self._enabled:
            await self.setup()

        vitals = await self.get_web_vitals()
        metrics = await self.get_metrics()

        cpu_profile = None
        if self._include_cpu_profile:
            cpu_profile = await self.profile_cpu()

        # resource summary from performance entries
        resource_summary: dict[str, int] = {}
        try:
            resources = await self._page.evaluate(
                "() => performance.getEntriesByType('resource').map(r => r.initiatorType)"
            )
            for r in resources:
                resource_summary[r] = resource_summary.get(r, 0) + 1
        except Exception:
            pass

        recommendations = self._generate_recommendations(vitals)

        return PerformanceReport(
            web_vitals=vitals,
            metrics=metrics,
            cpu_profile=cpu_profile,
            resource_summary=resource_summary,
            recommendations=recommendations,
        )

    async def teardown(self) -> None:
        try:
            await self._cdp.send("Performance.disable")
        except Exception:
            pass
        await super().teardown()


def _round_or_none(val: float | None, decimals: int = 2) -> float | None:
    if val is None:
        return None
    return round(val, decimals)
