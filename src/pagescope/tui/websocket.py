"""WebSocket tab -- real-time frame inspector with connection list and payload viewer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

from pagescope.models.websocket import WebSocketConnection, WebSocketFrame

WS_FILTERS = ["All", "Sent", "Received"]


def _format_ts(ts: float) -> str:
    try:
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%H:%M:%S.") + f"{int(ts * 1000) % 1000:03d}"
    except (OSError, ValueError):
        return ""


def _format_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _preview_payload(data: str, max_len: int = 60) -> str:
    """Short preview of payload data."""
    data = data.replace("\n", " ").replace("\r", "")
    if len(data) > max_len:
        return data[:max_len - 3] + "..."
    return data


class WebSocketTab(Widget):
    """WebSocket tab with connection list, frame table, and payload viewer."""

    BINDINGS = [
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("c", "clear_frames", "Clear", show=True),
    ]

    paused: reactive[bool] = reactive(False)
    active_filter: reactive[str] = reactive("All")
    search_query: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self._connections: dict[str, WebSocketConnection] = {}
        self._selected_conn_id: str | None = None
        self._selected_frame_index: int | None = None

    def compose(self) -> ComposeResult:
        # connection overview
        with Vertical(id="ws-overview"):
            yield Static("No WebSocket connections.", id="ws-stats-display")

        # filter bar
        with Horizontal(id="ws-filter-bar"):
            for name in WS_FILTERS:
                btn = Button(
                    name,
                    id=f"wsfilter-{name.lower()}",
                    classes="active" if name == "All" else "",
                )
                yield btn
            yield Input(placeholder="Search frames...", id="ws-search")

        # connection list (top) + frame table (bottom)
        with Vertical(id="ws-main"):
            yield DataTable(id="ws-conn-table")
            yield DataTable(id="ws-frame-table")

        # frame detail
        with Vertical(id="ws-detail"):
            yield Static("Select a frame to view payload.", id="ws-detail-content")

        # summary
        with Horizontal(id="ws-summary"):
            yield Label("0 connections", id="wssum-conns")
            yield Label("0 frames", id="wssum-frames")
            yield Label("", id="wssum-bytes")

    def on_mount(self) -> None:
        conn_table = self.query_one("#ws-conn-table", DataTable)
        conn_table.cursor_type = "row"
        conn_table.add_columns("Status", "URL", "Frames", "Sent", "Recv", "Size", "Duration")

        frame_table = self.query_one("#ws-frame-table", DataTable)
        frame_table.cursor_type = "row"
        frame_table.add_columns("Time", "Dir", "Length", "Preview")

    # ── Public API ──

    def add_frame(self, conn: WebSocketConnection, frame: WebSocketFrame) -> None:
        """Called in real-time when a WebSocket frame is sent/received."""
        if self.paused:
            return

        # update or add connection
        self._connections[conn.request_id] = conn
        self._update_conn_table()

        # if this connection is selected, add the frame row
        if self._selected_conn_id == conn.request_id:
            if self._matches_filter(frame):
                self._add_frame_row(frame, len(conn.frames) - 1)

        self._update_overview()
        self._update_summary()

    def update_connection(self, conn: WebSocketConnection) -> None:
        """Update connection status (e.g. closed)."""
        self._connections[conn.request_id] = conn
        self._update_conn_table()
        self._update_overview()

    # ── Filtering ──

    def _matches_filter(self, frame: WebSocketFrame) -> bool:
        f = self.active_filter
        if f == "Sent" and frame.direction != "sent":
            return False
        if f == "Received" and frame.direction != "received":
            return False
        if self.search_query and self.search_query.lower() not in frame.payload_data.lower():
            return False
        return True

    # ── Overview ──

    def _update_overview(self) -> None:
        total_conns = len(self._connections)
        open_conns = sum(1 for c in self._connections.values() if c.status == "open")
        total_frames = sum(c.frame_count for c in self._connections.values())

        if total_conns == 0:
            text = "No WebSocket connections."
        else:
            parts = [f"[bold]{total_conns}[/bold] connection{'s' if total_conns != 1 else ''}"]
            if open_conns > 0:
                parts.append(f"[green]{open_conns} open[/green]")
            parts.append(f"{total_frames} frames")
            text = "  ".join(parts)

        try:
            self.query_one("#ws-stats-display", Static).update(text)
        except NoMatches:
            pass

    # ── Connection table ──

    def _update_conn_table(self) -> None:
        try:
            table = self.query_one("#ws-conn-table", DataTable)
        except NoMatches:
            return
        table.clear()

        for conn in self._connections.values():
            status_style = "green" if conn.status == "open" else "dim"
            status = Text(conn.status.upper(), style=status_style)

            url = conn.url
            if len(url) > 60:
                url = "..." + url[-57:]

            duration = ""
            if conn.created_at:
                end = conn.closed_at or __import__("time").time()
                dur_s = end - conn.created_at
                if dur_s < 60:
                    duration = f"{dur_s:.1f}s"
                else:
                    duration = f"{dur_s / 60:.1f}m"

            table.add_row(
                status,
                url,
                str(conn.frame_count),
                str(conn.sent_count),
                str(conn.received_count),
                _format_size(conn.total_bytes),
                duration,
                key=conn.request_id,
            )

    # ── Frame table ──

    def _rebuild_frame_table(self) -> None:
        try:
            table = self.query_one("#ws-frame-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not self._selected_conn_id:
            return

        conn = self._connections.get(self._selected_conn_id)
        if not conn:
            return

        for i, frame in enumerate(conn.frames):
            if self._matches_filter(frame):
                self._add_frame_row(frame, i)

    def _add_frame_row(self, frame: WebSocketFrame, index: int) -> None:
        try:
            table = self.query_one("#ws-frame-table", DataTable)
        except NoMatches:
            return

        dir_style = "cyan" if frame.direction == "sent" else "green"
        dir_icon = "\u2191" if frame.direction == "sent" else "\u2193"

        table.add_row(
            _format_ts(frame.timestamp),
            Text(f"{dir_icon} {frame.direction}", style=dir_style),
            _format_size(frame.payload_length),
            _preview_payload(frame.payload_data),
            key=f"frame-{index}",
        )

    # ── Detail ──

    def _show_frame_detail(self, frame: WebSocketFrame) -> None:
        try:
            panel = self.query_one("#ws-detail")
            panel.add_class("visible")
            content = self.query_one("#ws-detail-content", Static)
        except NoMatches:
            return

        lines: list[str] = []
        dir_label = "[cyan]SENT \u2191[/cyan]" if frame.direction == "sent" else "[green]RECEIVED \u2193[/green]"
        lines.append(f"{dir_label}  {_format_ts(frame.timestamp)}  {_format_size(frame.payload_length)}")
        lines.append("")

        payload = frame.payload_data
        # try to pretty-print JSON
        try:
            parsed = json.loads(payload)
            formatted = json.dumps(parsed, indent=2)
            if len(formatted) > 3000:
                formatted = formatted[:3000] + "\n... (truncated)"
            lines.append("[bold]Payload (JSON)[/bold]")
            lines.append(formatted)
        except (json.JSONDecodeError, TypeError):
            if len(payload) > 3000:
                payload = payload[:3000] + "\n... (truncated)"
            lines.append("[bold]Payload[/bold]")
            lines.append(payload if payload else "[dim]<empty>[/dim]")

        content.update("\n".join(lines))

    # ── Summary ──

    def _update_summary(self) -> None:
        total_conns = len(self._connections)
        total_frames = sum(c.frame_count for c in self._connections.values())
        total_bytes = sum(c.total_bytes for c in self._connections.values())
        try:
            self.query_one("#wssum-conns", Label).update(f"{total_conns} connections")
            self.query_one("#wssum-frames", Label).update(f"{total_frames} frames")
            self.query_one("#wssum-bytes", Label).update(_format_size(total_bytes))
        except NoMatches:
            pass

    # ── Event handlers ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            conn_table = self.query_one("#ws-conn-table", DataTable)
            frame_table = self.query_one("#ws-frame-table", DataTable)
        except NoMatches:
            return

        key = event.row_key.value or ""

        # connection selected
        if event.data_table is conn_table:
            self._selected_conn_id = key
            self._rebuild_frame_table()

        # frame selected
        elif event.data_table is frame_table and key.startswith("frame-"):
            try:
                index = int(key.replace("frame-", ""))
                conn = self._connections.get(self._selected_conn_id or "")
                if conn and 0 <= index < len(conn.frames):
                    self._show_frame_detail(conn.frames[index])
            except (ValueError, IndexError):
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("wsfilter-"):
            filter_key = btn_id.replace("wsfilter-", "").capitalize()
            for name in WS_FILTERS:
                if name.lower() == btn_id.replace("wsfilter-", ""):
                    self.active_filter = name
                    break
            for btn in self.query("#ws-filter-bar Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._rebuild_frame_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ws-search":
            self.search_query = event.value
            self._rebuild_frame_table()

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#ws-search", Input).focus()
        except NoMatches:
            pass

    def action_clear_frames(self) -> None:
        for conn in self._connections.values():
            conn.frames.clear()
        try:
            self.query_one("#ws-frame-table", DataTable).clear()
        except NoMatches:
            pass
        self._update_overview()
        self._update_summary()

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
