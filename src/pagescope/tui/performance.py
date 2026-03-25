"""Performance tab -- Web Vitals dashboard, metrics table, CPU profile, recommendations."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static

from pagescope.models.performance import PerformanceReport, WebVitals

# ── Thresholds ──
# (good_max, needs_improvement_max)  -- values beyond the second are "poor"
_THRESHOLDS: dict[str, tuple[float, float]] = {
    "lcp_ms": (2500, 4000),
    "fcp_ms": (1800, 3000),
    "cls": (0.1, 0.25),
    "ttfb_ms": (800, 1800),
    "tbt_ms": (200, 600),
    "dcl_ms": (1500, 3500),
    "load_ms": (3000, 6000),
}


def _vital_rating(key: str, value: float | None) -> tuple[str, str]:
    """Return (display_value, rating_style) for a vital metric."""
    if value is None:
        return ("--", "dim")
    thresh = _THRESHOLDS.get(key)
    if thresh is None:
        return (f"{value:,.1f}", "dim")
    good, mid = thresh
    if key == "cls":
        display = f"{value:.3f}"
    elif value >= 1000:
        display = f"{value / 1000:.2f}s"
    else:
        display = f"{value:.0f}ms"
    if value <= good:
        return (display, "bold green")
    elif value <= mid:
        return (display, "bold yellow")
    else:
        return (display, "bold red")


# friendly labels for CDP metrics
_METRIC_LABELS: dict[str, str] = {
    "Timestamp": "Timestamp",
    "Documents": "Documents",
    "Frames": "Frames",
    "JSEventListeners": "JS Event Listeners",
    "Nodes": "DOM Nodes",
    "LayoutCount": "Layout Count",
    "RecalcStyleCount": "Recalc Style Count",
    "LayoutDuration": "Layout Duration",
    "RecalcStyleDuration": "Recalc Style Duration",
    "ScriptDuration": "Script Duration",
    "TaskDuration": "Task Duration",
    "JSHeapUsedSize": "JS Heap Used",
    "JSHeapTotalSize": "JS Heap Total",
    "FirstMeaningfulPaint": "First Meaningful Paint",
    "DomContentLoaded": "DOM Content Loaded",
    "NavigationStart": "Navigation Start",
}

# metrics that are byte values
_BYTE_METRICS = {"JSHeapUsedSize", "JSHeapTotalSize"}

# metrics that are durations (seconds)
_DURATION_METRICS = {"LayoutDuration", "RecalcStyleDuration", "ScriptDuration", "TaskDuration"}


def _format_metric_value(name: str, value: float) -> str:
    """Format a CDP metric value for display."""
    if name in _BYTE_METRICS:
        if value >= 1_048_576:
            return f"{value / 1_048_576:.1f} MB"
        elif value >= 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value:.0f} B"
    if name in _DURATION_METRICS:
        return f"{value * 1000:.1f}ms"
    if value == int(value) and value < 1_000_000:
        return f"{int(value):,}"
    if value > 1_000_000:
        return f"{value:,.0f}"
    return f"{value:.4f}"


# resource type to bar color name mapping
_RESOURCE_TYPE_COLORS: dict[str, str] = {
    "Document": "blue",
    "Script": "yellow",
    "Stylesheet": "green",
    "Image": "cyan",
    "Font": "text-dim",
    "Media": "cyan",
    "XHR": "accent",
    "Fetch": "accent",
    "WebSocket": "red",
    "Other": "text-dim",
}


def _flow_status_style(status: int | None) -> str:
    if status is None or status == 0:
        return "dim"
    if 200 <= status < 300:
        return "green"
    if 300 <= status < 400:
        return "yellow"
    return "red"


def _truncate_url(url: str, max_len: int = 40) -> str:
    """Extract path from URL and truncate."""
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path or "/"
        if len(path) > max_len:
            path = "…" + path[-(max_len - 1):]
        return path
    except Exception:
        return url[:max_len] if len(url) > max_len else url


# view modes
PERF_VIEWS = ["CPU Profile", "Page Flow", "Vitals", "Metrics", "Resources", "Recommendations"]


class PerformanceTab(Widget):
    """Performance tab with Web Vitals, CDP metrics, resource breakdown, and recommendations."""

    BINDINGS = [
        Binding("r", "request_rescan", "Re-scan", show=True),
    ]

    active_view: reactive[str] = reactive("CPU Profile")
    _scan_pending: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._report: PerformanceReport | None = None
        self._profiling: bool = False
        self._profile_callback: Any = None  # Set by app: async fn(duration) -> None
        self._requests: list = []  # Network requests for page flow view
        self._theme_colors: dict[str, str] | None = None  # Set by app

    def compose(self) -> ComposeResult:
        # Web Vitals summary bar at top
        with Horizontal(id="perf-vitals-bar"):
            yield Label("LCP: --", id="pv-lcp")
            yield Label("FCP: --", id="pv-fcp")
            yield Label("CLS: --", id="pv-cls")
            yield Label("TTFB: --", id="pv-ttfb")
            yield Label("TBT: --", id="pv-tbt")
            yield Label("DCL: --", id="pv-dcl")
            yield Label("Load: --", id="pv-load")

        # view tabs
        with Horizontal(id="perf-view-tabs"):
            for name in PERF_VIEWS:
                btn = Button(
                    name,
                    id=f"pview-{name.lower().replace(' ', '-')}",
                    classes="active" if name == "CPU Profile" else "",
                )
                yield btn

        # main content area -- all views stacked, toggle visibility
        with Vertical(id="perf-cpu-view"):
            with Horizontal(id="perf-cpu-controls"):
                yield Button("Start Profiling (5s)", id="cpu-start-btn", classes="cpu-btn")
                yield Button("Start (10s)", id="cpu-start-10-btn", classes="cpu-btn")
                yield Button("Stop", id="cpu-stop-btn", classes="cpu-btn hidden")
                yield Label("", id="cpu-status-label")
            yield Static("Click Start to capture a CPU profile.\n\nThe profiler records JavaScript execution for the specified duration, then shows the top functions by CPU time.", id="perf-cpu-content")

        with Vertical(id="perf-flow-view", classes="hidden"):
            yield Static("Capture network requests to see the page load flow.", id="perf-flow-content")

        with Vertical(id="perf-vitals-view", classes="hidden"):
            yield Static("Waiting for performance data...", id="perf-vitals-content")

        with Vertical(id="perf-metrics-view", classes="hidden"):
            yield DataTable(id="perf-metrics-table")

        with Vertical(id="perf-resources-view", classes="hidden"):
            yield DataTable(id="perf-resources-table")

        with Vertical(id="perf-recs-view", classes="hidden"):
            yield Static("Waiting for performance data...", id="perf-recs-content")

        # summary bar
        with Horizontal(id="perf-summary"):
            yield Label("No data", id="psum-status")
            yield Label("", id="psum-metrics")
            yield Label("", id="psum-resources")

    def on_mount(self) -> None:
        # setup metrics table
        metrics_table = self.query_one("#perf-metrics-table", DataTable)
        metrics_table.cursor_type = "row"
        metrics_table.add_columns("Metric", "Value")

        # setup resources table
        res_table = self.query_one("#perf-resources-table", DataTable)
        res_table.cursor_type = "row"
        res_table.add_columns("Resource Type", "Count", "Bar")

    # ── Public API ──

    def load_report(self, report: PerformanceReport) -> None:
        """Load a full performance report into the tab."""
        self._report = report
        self._update_vitals_bar(report.web_vitals)
        self._update_vitals_view(report.web_vitals)
        self._update_metrics_table(report)
        self._update_resources_table(report)
        self._update_recommendations(report)
        self._update_summary(report)
        if self._requests:
            self._update_flow_view()

    def load_cpu_profile(self, report: PerformanceReport) -> None:
        """Load CPU profile data (called after profiling completes)."""
        self._report = report
        self._update_cpu_view(report)

    # ── View switching ──

    def _switch_view(self, view_name: str) -> None:
        self.active_view = view_name
        view_ids = {
            "CPU Profile": "#perf-cpu-view",
            "Page Flow": "#perf-flow-view",
            "Vitals": "#perf-vitals-view",
            "Metrics": "#perf-metrics-view",
            "Resources": "#perf-resources-view",
            "Recommendations": "#perf-recs-view",
        }
        for name, vid in view_ids.items():
            try:
                w = self.query_one(vid)
                if name == view_name:
                    w.remove_class("hidden")
                else:
                    w.add_class("hidden")
            except NoMatches:
                pass

    # ── Vitals bar (always visible) ──

    def _update_vitals_bar(self, vitals: WebVitals) -> None:
        mapping = [
            ("pv-lcp", "LCP", "lcp_ms", vitals.lcp_ms),
            ("pv-fcp", "FCP", "fcp_ms", vitals.fcp_ms),
            ("pv-cls", "CLS", "cls", vitals.cls),
            ("pv-ttfb", "TTFB", "ttfb_ms", vitals.ttfb_ms),
            ("pv-tbt", "TBT", "tbt_ms", vitals.total_blocking_time_ms),
            ("pv-dcl", "DCL", "dcl_ms", vitals.dom_content_loaded_ms),
            ("pv-load", "Load", "load_ms", vitals.load_event_ms),
        ]
        for label_id, prefix, key, value in mapping:
            display, style = _vital_rating(key, value)
            try:
                lbl = self.query_one(f"#{label_id}", Label)
                lbl.update(f"{prefix}: [{style}]{display}[/{style}]")
            except NoMatches:
                pass

    # ── Vitals detail view ──

    def _update_vitals_view(self, vitals: WebVitals) -> None:
        lines: list[str] = []
        lines.append("[bold]Core Web Vitals[/bold]")
        lines.append("")

        entries = [
            ("Largest Contentful Paint (LCP)", "lcp_ms", vitals.lcp_ms, "Time until the largest visible element renders. Target: <2500ms"),
            ("First Contentful Paint (FCP)", "fcp_ms", vitals.fcp_ms, "Time until first text/image renders. Target: <1800ms"),
            ("Cumulative Layout Shift (CLS)", "cls", vitals.cls, "Visual stability score. Target: <0.1"),
            ("Time to First Byte (TTFB)", "ttfb_ms", vitals.ttfb_ms, "Server response time. Target: <800ms"),
            ("Total Blocking Time (TBT)", "tbt_ms", vitals.total_blocking_time_ms, "Sum of long task blocking time. Target: <200ms"),
        ]

        for label, key, value, desc in entries:
            display, style = _vital_rating(key, value)
            # rating indicator
            if value is None:
                indicator = "[dim]-[/dim]"
            elif style == "bold green":
                indicator = "[green]\u2713[/green]"
            elif style == "bold yellow":
                indicator = "[yellow]~[/yellow]"
            else:
                indicator = "[red]\u2717[/red]"
            lines.append(f"  {indicator}  [{style}]{display:>8}[/{style}]  {label}")
            lines.append(f"            [dim]{desc}[/dim]")
            lines.append("")

        lines.append("[bold]Page Load Timing[/bold]")
        lines.append("")
        dcl_display, dcl_style = _vital_rating("dcl_ms", vitals.dom_content_loaded_ms)
        load_display, load_style = _vital_rating("load_ms", vitals.load_event_ms)
        lines.append(f"  DOMContentLoaded:  [{dcl_style}]{dcl_display}[/{dcl_style}]")
        lines.append(f"  Load Event:        [{load_style}]{load_display}[/{load_style}]")

        try:
            self.query_one("#perf-vitals-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── Metrics table ──

    def _update_metrics_table(self, report: PerformanceReport) -> None:
        try:
            table = self.query_one("#perf-metrics-table", DataTable)
        except NoMatches:
            return
        table.clear()

        for m in report.metrics:
            label = _METRIC_LABELS.get(m.name, m.name)
            value = _format_metric_value(m.name, m.value)

            # highlight heap usage
            if m.name == "JSHeapUsedSize":
                total = next((x.value for x in report.metrics if x.name == "JSHeapTotalSize"), None)
                if total and total > 0:
                    pct = m.value / total * 100
                    if pct > 90:
                        value = f"[bold red]{value}[/bold red] ({pct:.0f}%)"
                    elif pct > 70:
                        value = f"[yellow]{value}[/yellow] ({pct:.0f}%)"
                    else:
                        value = f"{value} ({pct:.0f}%)"

            # highlight high DOM node counts
            if m.name == "Nodes" and m.value > 1500:
                if m.value > 3000:
                    value = f"[bold red]{value}[/bold red]"
                else:
                    value = f"[yellow]{value}[/yellow]"

            table.add_row(label, value)

    # ── Resources table ──

    def _update_resources_table(self, report: PerformanceReport) -> None:
        try:
            table = self.query_one("#perf-resources-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not report.resource_summary:
            table.add_row("No resources captured", "", "")
            return

        total = sum(report.resource_summary.values())
        # sort by count descending
        sorted_resources = sorted(report.resource_summary.items(), key=lambda x: x[1], reverse=True)
        max_count = sorted_resources[0][1] if sorted_resources else 1

        for rtype, count in sorted_resources:
            bar_width = int(count / max_count * 30) if max_count > 0 else 0
            pct = count / total * 100 if total > 0 else 0
            bar = Text()
            bar.append("\u2591" * bar_width, style="cyan on cyan")
            table.add_row(
                rtype,
                f"{count} ({pct:.0f}%)",
                bar,
            )

    # ── CPU Profile view ──

    def _update_cpu_view(self, report: PerformanceReport) -> None:
        lines: list[str] = []
        if report.cpu_profile is None:
            lines.append("No CPU profile data.")
            lines.append("")
            lines.append("Click [bold]Start Profiling[/bold] above to capture a CPU profile.")
        else:
            prof = report.cpu_profile
            lines.append(f"[bold]CPU Profile[/bold]  Duration: {prof.duration_ms:.0f}ms  Samples: {prof.total_samples}")
            lines.append("")
            lines.append(f"  {'Function':<40} {'Samples':>8} {'%':>6}  Bar")
            lines.append(f"  {'─' * 40} {'─' * 8} {'─' * 6}  {'─' * 20}")

            for fn in prof.top_functions:
                name = fn.get("function", "(anonymous)")
                if len(name) > 38:
                    name = name[:35] + "..."
                samples = fn.get("samples", 0)
                pct = fn.get("pct", 0)
                bar_width = int(pct / 100 * 20)
                bar = "\u2588" * bar_width

                if pct > 20:
                    style = "bold red"
                elif pct > 10:
                    style = "yellow"
                else:
                    style = "dim"

                lines.append(f"  {name:<40} {samples:>8} [{style}]{pct:>5.1f}%[/{style}]  [{style}]{bar}[/{style}]")

                url = fn.get("url", "")
                line = fn.get("line", 0)
                if url:
                    # trim URL
                    short_url = url.rsplit("/", 1)[-1] if "/" in url else url
                    if len(short_url) > 50:
                        short_url = short_url[:47] + "..."
                    lines.append(f"  [dim]  {short_url}:{line}[/dim]")

        try:
            self.query_one("#perf-cpu-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── Page Flow view ──

    def add_request(self, request) -> None:
        """Add a network request for the page flow visualization."""
        self._requests.append(request)

    def load_requests(self, requests: list) -> None:
        """Load a batch of network requests and update the flow view."""
        self._requests = list(requests)
        self._update_flow_view()

    def _update_flow_view(self) -> None:
        """Build the ASCII page load flow visualization."""
        lines: list[str] = []
        vitals = self._report.web_vitals if self._report else None

        # ── Milestone Timeline ──
        if vitals:
            # find the max time for scaling
            times = [
                ("TTFB", "ttfb_ms", vitals.ttfb_ms),
                ("FCP", "fcp_ms", vitals.fcp_ms),
                ("DCL", "dcl_ms", vitals.dom_content_loaded_ms),
                ("LCP", "lcp_ms", vitals.lcp_ms),
                ("Load", "load_ms", vitals.load_event_ms),
            ]
            valid_times = [(n, k, v) for n, k, v in times if v is not None]

            if valid_times:
                max_ms = max(v for _, _, v in valid_times)
                bar_width = 50

                lines.append("[bold]Page Load Timeline[/bold]")
                lines.append("[dim]" + "─" * 60 + "[/dim]")
                lines.append("")

                for name, key, value in times:
                    if value is None:
                        lines.append(f"  {name:<6} {'--':>8}  [dim]no data[/dim]")
                        continue

                    display, style = _vital_rating(key, value)
                    fill = int(value / max_ms * bar_width) if max_ms > 0 else 0
                    fill = max(1, fill)
                    bar = "█" * fill + "░" * (bar_width - fill)
                    lines.append(f"  {name:<6} [{style}]{display:>8}[/{style}]  [{style}]{bar}[/{style}]")

                lines.append("")
        else:
            lines.append("[dim]Waiting for performance data...[/dim]")
            lines.append("")

        # ── Resource Waterfall ──
        if self._requests:
            sorted_reqs = sorted(self._requests, key=lambda r: r.start_time)
            total = len(sorted_reqs)
            display_reqs = sorted_reqs[:60]

            # find time bounds
            page_start = display_reqs[0].start_time
            page_end = max(
                (r.end_time or r.start_time for r in display_reqs),
                default=page_start,
            )
            span = page_end - page_start
            if span <= 0:
                span = 1

            total_time_ms = span * 1000
            time_label = f"{total_time_ms:.0f}ms" if total_time_ms < 1000 else f"{total_time_ms / 1000:.2f}s"

            lines.append(f"[bold]Resource Waterfall[/bold]  ({total} requests, {time_label})")
            lines.append("[dim]" + "─" * 60 + "[/dim]")

            # time scale header
            bar_width = 40
            markers = ["0"]
            for i in range(1, 5):
                t = total_time_ms * i / 4
                markers.append(f"{t:.0f}ms" if t < 1000 else f"{t / 1000:.1f}s")
            # build scale line
            scale = "  " + " " * 6 + " " * 5  # method + status padding
            segment = bar_width // 4
            for i, m in enumerate(markers):
                if i == 0:
                    scale += m.ljust(segment)
                elif i < len(markers) - 1:
                    scale += m.ljust(segment)
                else:
                    scale += m
            lines.append(f"[dim]{scale}[/dim]")
            lines.append("")

            for req in display_reqs:
                method = (req.method or "GET")[:4]
                status = req.response_status or 0
                status_str = str(status) if status else "ERR"
                s_style = _flow_status_style(status)

                # calculate bar position
                left = max(0, (req.start_time - page_start) / span)
                right = min(1, ((req.end_time or req.start_time) - page_start) / span)
                bar_start = int(left * bar_width)
                bar_end = max(bar_start + 1, int(right * bar_width))

                # determine bar color by resource type
                rtype = getattr(req, "resource_type", "Other") or "Other"
                color_key = _RESOURCE_TYPE_COLORS.get(rtype, "text-dim")

                # build the bar
                queued = "·" * bar_start
                active = "█" * (bar_end - bar_start)
                trail = " " * (bar_width - bar_end)

                # timing
                req_ms = ((req.end_time or req.start_time) - req.start_time) * 1000
                if req_ms < 1000:
                    time_str = f"{req_ms:.0f}ms"
                else:
                    time_str = f"{req_ms / 1000:.2f}s"

                path = _truncate_url(req.url, 30)

                lines.append(
                    f"  {method:<4} [{s_style}]{status_str:>3}[/{s_style}]  "
                    f"[dim]{queued}[/dim][{color_key}]{active}[/{color_key}]{trail}  "
                    f"{time_str:>7}  [dim]{path}[/dim]"
                )

            if total > 60:
                lines.append(f"  [dim]... and {total - 60} more requests[/dim]")
        else:
            lines.append("[dim]No network requests captured yet.[/dim]")

        try:
            self.query_one("#perf-flow-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── Recommendations ──

    def _update_recommendations(self, report: PerformanceReport) -> None:
        lines: list[str] = []

        if not report.recommendations:
            lines.append("[bold green]\u2713 All Core Web Vitals within targets![/bold green]")
            lines.append("")
            lines.append("[dim]No performance issues detected based on current thresholds.[/dim]")
        else:
            lines.append(f"[bold yellow]{len(report.recommendations)} Recommendation{'s' if len(report.recommendations) != 1 else ''}[/bold yellow]")
            lines.append("")
            for i, rec in enumerate(report.recommendations, 1):
                lines.append(f"  [bold]{i}.[/bold] {rec}")
                lines.append("")

        # add resource insights if available
        if report.resource_summary:
            total = sum(report.resource_summary.values())
            lines.append(f"[bold]Resource Summary[/bold]  ({total} total)")
            lines.append("")
            for rtype, count in sorted(report.resource_summary.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {rtype}: {count}")

        try:
            self.query_one("#perf-recs-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── Summary bar ──

    def _update_summary(self, report: PerformanceReport) -> None:
        v = report.web_vitals
        try:
            # status
            if report.recommendations:
                self.query_one("#psum-status", Label).update(
                    f"{len(report.recommendations)} issues"
                )
            else:
                self.query_one("#psum-status", Label).update("All vitals OK")

            # metrics count
            self.query_one("#psum-metrics", Label).update(
                f"{len(report.metrics)} metrics"
            )

            # resources
            total_res = sum(report.resource_summary.values()) if report.resource_summary else 0
            self.query_one("#psum-resources", Label).update(
                f"{total_res} resources"
            )
        except NoMatches:
            pass

    # ── Event handlers ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("pview-"):
            # Map button IDs back to view names via case-insensitive match
            btn_key = btn_id.replace("pview-", "").replace("-", " ")
            matched = btn_key
            for v in PERF_VIEWS:
                if v.lower() == btn_key:
                    matched = v
                    break

            self._switch_view(matched)
            for btn in self.query("#perf-view-tabs Button"):
                btn.remove_class("active")
            event.button.add_class("active")

        elif btn_id == "cpu-start-btn":
            self._start_profile(5)
        elif btn_id == "cpu-start-10-btn":
            self._start_profile(10)
        elif btn_id == "cpu-stop-btn":
            # stop is handled by the duration timeout, but this provides
            # visual feedback that profiling will end
            pass

    def _start_profile(self, duration: int) -> None:
        """Trigger CPU profiling via the app callback."""
        if self._profiling or not self._profile_callback:
            return
        self._profiling = True
        try:
            # update UI
            self.query_one("#cpu-start-btn", Button).add_class("hidden")
            self.query_one("#cpu-start-10-btn", Button).add_class("hidden")
            self.query_one("#cpu-stop-btn", Button).remove_class("hidden")
            self.query_one("#cpu-status-label", Label).update(
                f"Profiling for {duration}s..."
            )
            self.query_one("#perf-cpu-content", Static).update(
                f"[bold]Recording CPU profile...[/bold]\n\n"
                f"Capturing {duration} seconds of JavaScript execution.\n"
                f"Interact with the page in your browser to generate activity."
            )
        except NoMatches:
            pass
        # fire the callback (app handles the async work)
        self._profile_callback(duration)

    def on_profile_complete(self) -> None:
        """Called by the app when profiling finishes."""
        self._profiling = False
        try:
            self.query_one("#cpu-start-btn", Button).remove_class("hidden")
            self.query_one("#cpu-start-10-btn", Button).remove_class("hidden")
            self.query_one("#cpu-stop-btn", Button).add_class("hidden")
            self.query_one("#cpu-status-label", Label).update("Profile complete")
        except NoMatches:
            pass

    def action_request_rescan(self) -> None:
        """Request a re-scan from the app."""
        self._scan_pending = True
