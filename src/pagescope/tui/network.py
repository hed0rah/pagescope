"""Network tab -- real-time request table with filtering and detail panel."""

from __future__ import annotations

import json
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

from pagescope.tui.replay import ReplayPanel


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "--"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_time(start: float, end: float | None) -> str:
    if end is None:
        return "pending"
    ms = (end - start) * 1000
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} s"


def _status_style(status: int | None) -> str:
    if status is None or status == 0:
        return "dim"
    if 200 <= status < 300:
        return "green"
    if 300 <= status < 400:
        return "yellow"
    return "red"


def _waterfall_bar(
    start: float,
    end: float | None,
    page_start: float,
    page_end: float,
    timing: dict | None = None,
    colors: dict[str, str] | None = None,
) -> Text:
    """Render a waterfall bar with timing-phase coloring.

    Uses background-colored spaces so that DataTable cursor highlighting
    (which overrides foreground color) cannot wash out the bar colors.
    """
    if end is None or page_end <= page_start:
        return Text("")
    span = page_end - page_start
    if span == 0:
        c = colors.get("wf-download", "cyan") if colors else "cyan"
        return Text(" ", style=f"on {c}")

    width = 50
    total_ms = (end - start) * 1000

    # if we have timing data and theme colors, render phase-colored segments
    if timing and colors:
        # calculate phase durations in ms
        dns = max(0, timing.get("dnsEnd", 0) - timing.get("dnsStart", 0))
        connect = max(0, timing.get("connectEnd", 0) - timing.get("connectStart", 0))
        ssl = max(0, timing.get("sslEnd", 0) - timing.get("sslStart", 0))
        # connect includes SSL, so subtract SSL from connect
        connect = max(0, connect - ssl)
        send = max(0, timing.get("sendEnd", 0) - timing.get("sendStart", 0))
        wait = max(0, timing.get("receiveHeadersEnd", 0) - timing.get("sendEnd", 0))
        # download = total - (dns + connect + ssl + send + wait)
        accounted = dns + connect + ssl + send + wait
        download = max(0, total_ms - accounted)

        # calculate bar start position (queued/waiting before request starts)
        left = max(0, (start - page_start) / span)
        right = min(1, (end - page_start) / span)
        bar_start = int(left * width)
        bar_width = max(1, int(right * width) - bar_start)

        # build the phases proportionally within the bar
        phases = [
            (dns, colors["wf-dns"]),
            (connect, colors["wf-connect"]),
            (ssl, colors["wf-ssl"]),
            (send, colors["wf-connect"]),
            (wait, colors["wf-wait"]),
            (download, colors["wf-download"]),
        ]

        result = Text()
        # leading space (queued period) -- transparent bg
        if bar_start > 0:
            result.append(" " * bar_start)

        # use ░ with foreground = background so it looks solid normally.
        # when the DataTable cursor overrides foreground to a lighter color,
        # the ░ pattern subtly reveals that lighter color (~25% bleed).
        chars_used = 0
        for duration, color in phases:
            if total_ms <= 0:
                break
            phase_chars = max(0, round(duration / total_ms * bar_width))
            if phase_chars > 0 and chars_used < bar_width:
                take = min(phase_chars, bar_width - chars_used)
                result.append("░" * take, style=f"{color} on {color}")
                chars_used += take

        # fill remaining if rounding left gaps
        if chars_used < bar_width:
            c = colors["wf-download"]
            result.append("░" * (bar_width - chars_used), style=f"{c} on {c}")

        return result

    # fallback: single-color bar with theme accent
    left = max(0, (start - page_start) / span)
    right = min(1, (end - page_start) / span)
    bar_start = int(left * width)
    bar_end = max(bar_start + 1, int(right * width))

    result = Text()
    if bar_start > 0:
        result.append(" " * bar_start)
    bar_color = colors.get("wf-download", "cyan") if colors else "cyan"
    result.append("░" * (bar_end - bar_start), style=f"{bar_color} on {bar_color}")
    return result


# resource type filter mapping
RESOURCE_FILTERS = {
    "All": None,
    "XHR": {"XHR", "Fetch"},
    "JS": {"Script"},
    "CSS": {"Stylesheet"},
    "Img": {"Image"},
    "Font": {"Font"},
    "Media": {"Media"},
    "WS": {"WebSocket"},
    "Other": "other",
}


class NetworkTab(Widget):
    """Full network tab with table, filters, detail panel, and summary."""

    BINDINGS = [
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("c", "clear_requests", "Clear", show=True),
        Binding("b", "toggle_body_search", "Body Search", show=True),
        Binding("r", "replay_request", "Replay", show=True),
    ]

    paused: reactive[bool] = reactive(False)
    active_filter: reactive[str] = reactive("All")
    search_query: reactive[str] = reactive("")
    selected_request: reactive[Any] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._requests: list = []
        self._page_start: float = 0
        self._page_end: float = 0
        self._total_bytes: int = 0
        self._detail_sub_tab: str = "headers"
        self._body_search_visible: bool = False
        self._body_search_results: list = []
        self._body_search_callback: Any = None  # Set by app
        self._replay_callback: Any = None  # Set by app
        self._theme_colors: dict[str, str] | None = None  # Set by app on theme change

    def compose(self) -> ComposeResult:
        # filter bar
        with Horizontal(id="filter-bar"):
            for name in RESOURCE_FILTERS:
                btn = Button(name, id=f"filter-{name.lower()}", classes="active" if name == "All" else "")
                yield btn
            yield Input(placeholder="Search URLs...", id="filter-input")

        # body search bar (hidden by default)
        with Horizontal(id="body-search-bar", classes="hidden"):
            yield Input(
                placeholder="Regex pattern to search response bodies (e.g. flag\\{.*\\}, password, api_key)...",
                id="body-search-input",
            )

        # main area: table + detail
        with Vertical(id="main-split"):
            yield DataTable(id="request-table")
            with Vertical(id="detail-panel"):
                with Horizontal(id="detail-tabs"):
                    yield Button("Headers", id="dtab-headers", classes="active")
                    yield Button("Timing", id="dtab-timing")
                    yield Button("Response", id="dtab-response")
                    yield Button("Initiator", id="dtab-initiator")
                yield Static("Select a request to view details.", id="detail-content")

        # body search results (hidden by default)
        with Vertical(id="body-search-results", classes="hidden"):
            yield DataTable(id="body-search-table")

        # replay panel (hidden by default)
        yield ReplayPanel()

        # summary bar
        with Horizontal(id="summary-bar"):
            yield Label("0 requests", id="sum-requests")
            yield Label("0 B transferred", id="sum-size")
            yield Label("", id="sum-time")

    def on_mount(self) -> None:
        table = self.query_one("#request-table", DataTable)
        table.cursor_type = "row"
        keys = table.add_columns(
            "Status", "Method", "URL", "Type", "Size", "Time", "Waterfall"
        )
        self._waterfall_col_key = keys[-1]

        # body search results table
        bs_table = self.query_one("#body-search-table", DataTable)
        bs_table.cursor_type = "row"
        bs_table.add_columns("URL", "Type", "Line", "Match", "Context")

    # ── Public API for the app to push data ──

    def add_request(self, request) -> None:
        """Called from the app when a network request completes."""
        if self.paused:
            return

        # skip chrome internal requests -- they skew the timeline
        # and never appear in real DevTools
        url = getattr(request, "url", "")
        if url.startswith("chrome://") or url.startswith("chrome-extension://"):
            return

        # deduplicate -- CDP can fire duplicate events for the same request
        for existing in self._requests:
            if existing.request_id == request.request_id:
                return

        self._requests.append(request)

        # update timeline bounds and track if they changed
        old_start, old_end = self._page_start, self._page_end
        if not self._page_start or request.start_time < self._page_start:
            self._page_start = request.start_time
        if request.end_time and (not self._page_end or request.end_time > self._page_end):
            self._page_end = request.end_time

        self._total_bytes += request.response_size or 0

        timeline_changed = (self._page_start != old_start or self._page_end != old_end)

        if timeline_changed and len(self._requests) > 1:
            # timeline shifted -- recalculate all waterfall bars
            self._rebuild_table()
        else:
            if not self._matches_filter(request):
                self._update_summary()
                return
            self._add_row(request)

        if timeline_changed:
            self._update_waterfall_header()

        self._update_summary()

    def _matches_filter(self, request) -> bool:
        """Check if request matches current filter and search."""
        # type filter
        filter_set = RESOURCE_FILTERS.get(self.active_filter)
        if filter_set is not None:
            if filter_set == "other":
                known = set()
                for v in RESOURCE_FILTERS.values():
                    if isinstance(v, set):
                        known |= v
                if request.resource_type in known:
                    return False
            elif isinstance(filter_set, set) and request.resource_type not in filter_set:
                return False

        # search filter
        if self.search_query and self.search_query.lower() not in request.url.lower():
            return False

        return True

    def _add_row(self, request) -> None:
        status = request.response_status or 0
        style = _status_style(status)
        status_text = Text(str(status) if status else "ERR", style=style)

        url_display = request.url
        if len(url_display) > 80:
            url_display = url_display[:77] + "..."

        table = self.query_one("#request-table", DataTable)
        try:
            table.add_row(
                status_text,
                request.method,
                url_display,
                request.resource_type,
                _format_size(request.response_size),
                _format_time(request.start_time, request.end_time),
                _waterfall_bar(
                    request.start_time, request.end_time,
                    self._page_start, self._page_end,
                    timing=getattr(request, "timing", None),
                    colors=self._theme_colors,
                ),
                key=request.request_id,
            )
        except Exception:
            pass  # Duplicate key or widget not mounted

    def _rebuild_table(self) -> None:
        """Rebuild table with current filters."""
        table = self.query_one("#request-table", DataTable)
        table.clear()
        for req in self._requests:
            if self._matches_filter(req):
                self._add_row(req)

    def _update_waterfall_header(self) -> None:
        """Update the waterfall column header with a timeline ruler."""
        if not self._page_start or not self._page_end:
            return
        span_ms = (self._page_end - self._page_start) * 1000
        if span_ms <= 0:
            return

        # format the total time nicely
        if span_ms >= 1000:
            total = f"{span_ms / 1000:.1f}s"
        else:
            total = f"{span_ms:.0f}ms"

        # pick a nice midpoint label
        mid_ms = span_ms / 2
        if mid_ms >= 1000:
            mid = f"{mid_ms / 1000:.1f}s"
        else:
            mid = f"{mid_ms:.0f}ms"

        # build a 50-char ruler: "0ms ──────── 250ms ──────── 500ms"
        w = 50
        left_label = "0"
        # distribute labels across the width
        gap1 = w // 2 - len(left_label) - len(mid) // 2
        gap2 = w - (len(left_label) + gap1 + len(mid)) - len(total)
        ruler = left_label + "─" * max(1, gap1) + mid + "─" * max(1, gap2) + total

        try:
            table = self.query_one("#request-table", DataTable)
            col = table.columns[self._waterfall_col_key]
            from rich.text import Text as RichText
            col.label = RichText(ruler)
        except Exception:
            pass

    def _update_summary(self) -> None:
        visible = sum(1 for r in self._requests if self._matches_filter(r))
        total = len(self._requests)
        try:
            self.query_one("#sum-requests", Label).update(
                f"{visible}/{total} requests" if visible != total else f"{total} requests"
            )
            self.query_one("#sum-size", Label).update(f"{_format_size(self._total_bytes)} transferred")
            if self._page_start and self._page_end:
                elapsed = (self._page_end - self._page_start) * 1000
                self.query_one("#sum-time", Label).update(f"{elapsed:.0f} ms")
        except NoMatches:
            pass

    # ── Detail panel ──

    def _show_detail(self, request) -> None:
        self.selected_request = request
        try:
            panel = self.query_one("#detail-panel")
            panel.add_class("visible")
        except NoMatches:
            pass
        self._render_detail_tab()

    def _render_detail_tab(self) -> None:
        req = self.selected_request
        if req is None:
            return

        content = self.query_one("#detail-content", Static)

        if self._detail_sub_tab == "headers":
            lines = []
            lines.append("[bold]Request Headers[/bold]")
            for k, v in (req.request_headers or {}).items():
                lines.append(f"  [dim]{k}:[/dim] {v}")
            lines.append("")
            lines.append("[bold]Response Headers[/bold]")
            for k, v in (req.response_headers or {}).items():
                lines.append(f"  [dim]{k}:[/dim] {v}")
            content.update("\n".join(lines))

        elif self._detail_sub_tab == "timing":
            if req.timing:
                lines = ["[bold]Timing Breakdown[/bold]"]
                t = req.timing
                dns = t.get("dnsEnd", 0) - t.get("dnsStart", 0)
                connect = t.get("connectEnd", 0) - t.get("connectStart", 0)
                ssl = t.get("sslEnd", 0) - t.get("sslStart", 0)
                ttfb = t.get("receiveHeadersEnd", 0) - t.get("sendEnd", 0)
                total = (req.end_time - req.start_time) * 1000 if req.end_time else 0
                lines.append(f"  DNS:     [cyan]{dns:.1f} ms[/cyan]")
                lines.append(f"  Connect: [cyan]{connect:.1f} ms[/cyan]")
                lines.append(f"  SSL:     [cyan]{ssl:.1f} ms[/cyan]")
                lines.append(f"  TTFB:    [yellow]{ttfb:.1f} ms[/yellow]")
                lines.append(f"  Total:   [bold]{total:.1f} ms[/bold]")
                content.update("\n".join(lines))
            else:
                content.update("[dim]No timing data available.[/dim]")

        elif self._detail_sub_tab == "response":
            body = req.response_body
            if body:
                try:
                    parsed = json.loads(body)
                    content.update(json.dumps(parsed, indent=2)[:2000])
                except (json.JSONDecodeError, TypeError):
                    content.update(str(body)[:2000])
            else:
                content.update("[dim]Response body not captured.[/dim]")

        elif self._detail_sub_tab == "initiator":
            init = req.initiator or {}
            if init:
                lines = [f"[bold]Type:[/bold] {init.get('type', 'unknown')}"]
                stack = init.get("stack", {})
                frames = stack.get("callFrames", [])
                for frame in frames[:5]:
                    fn = frame.get("functionName", "(anonymous)")
                    url = frame.get("url", "")
                    line = frame.get("lineNumber", 0)
                    lines.append(f"  {fn} @ {url}:{line}")
                content.update("\n".join(lines))
            else:
                content.update("[dim]No initiator data.[/dim]")

    # ── Event handlers ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        for req in self._requests:
            if req.request_id == key:
                self._show_detail(req)
                break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        # filter buttons
        if btn_id.startswith("filter-"):
            filter_name = btn_id.replace("filter-", "").capitalize()
            # Map back to proper case
            for name in RESOURCE_FILTERS:
                if name.lower() == btn_id.replace("filter-", ""):
                    filter_name = name
                    break
            self.active_filter = filter_name
            # update button styles
            for btn in self.query("#filter-bar Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._rebuild_table()

        # detail sub-tabs
        elif btn_id.startswith("dtab-"):
            self._detail_sub_tab = btn_id.replace("dtab-", "")
            for btn in self.query("#detail-tabs Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._render_detail_tab()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "body-search-input" and self._body_search_callback:
            pattern = event.value.strip()
            if pattern:
                self._body_search_callback(pattern)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self.search_query = event.value
            self._rebuild_table()

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#filter-input", Input).focus()
        except NoMatches:
            pass

    def action_focus_search(self) -> None:
        self.action_focus_filter()

    def action_clear_requests(self) -> None:
        self._requests.clear()
        self._total_bytes = 0
        self._page_start = 0
        self._page_end = 0
        table = self.query_one("#request-table", DataTable)
        table.clear()
        self._update_summary()
        # reset waterfall header
        try:
            col = table.columns[self._waterfall_col_key]
            from rich.text import Text as RichText
            col.label = RichText("Waterfall")
        except Exception:
            pass

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused

    # ── Body Search ──

    def action_toggle_body_search(self) -> None:
        """Toggle the response body search panel."""
        self._body_search_visible = not self._body_search_visible
        try:
            bar = self.query_one("#body-search-bar")
            results = self.query_one("#body-search-results")
            main = self.query_one("#main-split")
            if self._body_search_visible:
                bar.remove_class("hidden")
                self.query_one("#body-search-input", Input).focus()
            else:
                bar.add_class("hidden")
                results.add_class("hidden")
                main.remove_class("hidden")
        except NoMatches:
            pass

    def action_replay_request(self) -> None:
        """Open the replay panel for the currently selected request."""
        if self.selected_request is None:
            return
        try:
            replay = self.query_one(ReplayPanel)
            replay.load_request(self.selected_request)
            replay._replay_callback = self._replay_callback
            replay.show()
            # hide main split to make room
            self.query_one("#main-split").add_class("hidden")
        except NoMatches:
            pass

    def close_replay(self) -> None:
        """Close the replay panel and restore the main view."""
        try:
            self.query_one(ReplayPanel).hide()
            self.query_one("#main-split").remove_class("hidden")
        except NoMatches:
            pass

    def load_body_search_results(self, matches: list) -> None:
        """Load response body search results from the app."""
        self._body_search_results = matches
        try:
            table = self.query_one("#body-search-table", DataTable)
            results = self.query_one("#body-search-results")
            main = self.query_one("#main-split")
        except NoMatches:
            return

        table.clear()
        if not matches:
            results.remove_class("hidden")
            main.add_class("hidden")
            table.add_row("", "", "", "No matches found", "")
            return

        results.remove_class("hidden")
        main.add_class("hidden")

        for i, m in enumerate(matches[:200]):
            url = m.url
            if len(url) > 50:
                url = "..." + url[-47:]
            context = m.context
            if len(context) > 60:
                context = context[:57] + "..."
            match_text = m.match_text
            if len(match_text) > 30:
                match_text = match_text[:27] + "..."

            style = "bold red" if any(
                kw in m.match_text.lower()
                for kw in ("password", "flag{", "api_key", "secret", "token")
            ) else ""

            table.add_row(
                url,
                m.content_type.split(";")[0] if m.content_type else "",
                str(m.line_number),
                Text(match_text, style=style) if style else match_text,
                context,
                key=str(i),
            )

        # update summary
        try:
            self.query_one("#sum-requests", Label).update(
                f"{len(matches)} matches in response bodies"
            )
        except NoMatches:
            pass
