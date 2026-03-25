"""Console tab -- real-time log stream with level filtering, stack trace expansion, and interactive JS evaluation."""

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
from textual.widgets import Button, DataTable, Input, Label, Static, TextArea

class _ClickableLabel(Label):
    """A Label that fires a Button.Pressed-like message on click."""

    def on_click(self, event) -> None:
        event.stop()
        # bubble a button pressed so the parent can handle it uniformly
        self.post_message(Button.Pressed(self))  # type: ignore[arg-type]

from pagescope.models.console import ConsoleEntry, ConsoleLevel, ExceptionInfo, Violation


# level display config: (label, style)
_LEVEL_STYLES = {
    ConsoleLevel.ERROR: ("ERR", "bold red"),
    ConsoleLevel.WARNING: ("WRN", "yellow"),
    ConsoleLevel.INFO: ("INF", "blue"),
    ConsoleLevel.LOG: ("LOG", "dim"),
    ConsoleLevel.DEBUG: ("DBG", "dim cyan"),
    ConsoleLevel.VERBOSE: ("VRB", "dim"),
}

# special level styles for eval input/output
_EVAL_INPUT_STYLE = (">>>", "bold cyan")
_EVAL_RESULT_STYLE = ("<<<", "bold green")
_EVAL_ERROR_STYLE = ("ERR", "bold red")

# filter buttons
LEVEL_FILTERS = ["All", "Errors", "Warnings", "Info", "Debug"]

_FILTER_TO_LEVELS = {
    "All": None,
    "Errors": {ConsoleLevel.ERROR},
    "Warnings": {ConsoleLevel.WARNING},
    "Info": {ConsoleLevel.INFO, ConsoleLevel.LOG},
    "Debug": {ConsoleLevel.DEBUG, ConsoleLevel.VERBOSE},
}


def _format_timestamp(ts: float) -> str:
    if ts <= 0:
        return ""
    try:
        # CDP timestamps are in ms since epoch
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%H:%M:%S.") + f"{int(ts % 1000):03d}"
    except (OSError, ValueError):
        return ""


def _now_ms() -> float:
    """Return current time in milliseconds since epoch (matching CDP timestamp format)."""
    return datetime.now().timestamp() * 1000


def _format_source(url: str, line: int | None) -> str:
    if not url:
        return ""
    # trim to just filename
    parts = url.rstrip("/").rsplit("/", 1)
    name = parts[-1] if parts else url
    if len(name) > 30:
        name = name[:27] + "..."
    if line is not None:
        return f"{name}:{line}"
    return name


class ConsoleTab(Widget):
    """Console tab with real-time log stream, level filters, detail view, and interactive JS eval."""

    BINDINGS = [
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("c", "clear_console", "Clear", show=True),
        Binding("e", "focus_eval", "Eval", show=True),
    ]

    paused: reactive[bool] = reactive(False)
    active_filter: reactive[str] = reactive("All")
    search_query: reactive[str] = reactive("")
    selected_row_data: reactive[Any] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[dict] = []  # Unified list: entry/exception/violation dicts
        self._counts = {"error": 0, "warning": 0, "info": 0, "debug": 0, "exception": 0, "violation": 0}
        self._eval_callback: Any = None  # Set by app.py: async fn(expression) -> result
        self._history: list[str] = []  # Command history
        self._history_index: int = -1  # Current position in history (-1 = not browsing)
        self._editor_expanded: bool = False

    def compose(self) -> ComposeResult:
        # filter bar
        with Horizontal(id="console-filter-bar"):
            for name in LEVEL_FILTERS:
                btn = Button(name, id=f"clevel-{name.lower()}", classes="active" if name == "All" else "")
                yield btn
            yield Input(placeholder="Search messages...", id="console-search")

        # main area: log table + detail
        with Vertical(id="console-main"):
            yield DataTable(id="console-table")
            with Vertical(id="console-detail"):
                yield Static("Select a message to view details.", id="console-detail-content")

        # expanded JS editor (hidden by default)
        with Vertical(id="console-editor-panel", classes="hidden"):
            with Horizontal(id="console-editor-bar"):
                yield Label("> js", id="console-editor-label")
                yield Button(" \u25b6 ", id="console-editor-run", classes="editor-btn")
                yield Button(" \u25bc ", id="console-editor-collapse", classes="editor-btn")
            yield TextArea(id="console-editor-textarea", language="javascript")

        # console input bar (interactive JS eval)
        with Horizontal(id="console-input-bar"):
            yield Label(">", id="console-prompt")
            yield Input(placeholder="Evaluate JavaScript...", id="console-eval-input")
            yield _ClickableLabel("\u25b2", id="console-expand-btn")

        # summary bar
        with Horizontal(id="console-summary"):
            yield Label("0 messages", id="csum-total")
            yield Label("0 errors", id="csum-errors")
            yield Label("0 warnings", id="csum-warnings")
            yield Label("0 exceptions", id="csum-exceptions")

    def on_mount(self) -> None:
        table = self.query_one("#console-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Time", "Level", "Message", "Source")

    # ── Public API ──

    def add_entry(self, entry: ConsoleEntry) -> None:
        """Add a console message."""
        if self.paused:
            return

        level_label, _ = _LEVEL_STYLES.get(entry.level, ("LOG", "dim"))
        record = {
            "kind": "entry",
            "level": entry.level,
            "level_label": level_label,
            "text": entry.text,
            "source": _format_source(entry.url, entry.line_number),
            "timestamp": _format_timestamp(entry.timestamp),
            "full_url": entry.url,
            "line": entry.line_number,
            "col": entry.column_number,
            "stack": None,
        }
        self._entries.append(record)

        # update counts
        if entry.level == ConsoleLevel.ERROR:
            self._counts["error"] += 1
        elif entry.level == ConsoleLevel.WARNING:
            self._counts["warning"] += 1
        elif entry.level in (ConsoleLevel.INFO, ConsoleLevel.LOG):
            self._counts["info"] += 1
        else:
            self._counts["debug"] += 1

        if self._matches_filter(record):
            self._add_row(record, len(self._entries) - 1)
        self._update_summary()

    def add_exception(self, exc: ExceptionInfo) -> None:
        """Add an unhandled exception."""
        if self.paused:
            return

        record = {
            "kind": "exception",
            "level": ConsoleLevel.ERROR,
            "level_label": "EXC",
            "text": exc.message,
            "source": _format_source(exc.url, exc.line_number),
            "timestamp": _format_timestamp(exc.timestamp),
            "full_url": exc.url,
            "line": exc.line_number,
            "col": exc.column_number,
            "stack": exc.stack_trace,
            "description": exc.description,
        }
        self._entries.append(record)
        self._counts["exception"] += 1
        self._counts["error"] += 1

        if self._matches_filter(record):
            self._add_row(record, len(self._entries) - 1)
        self._update_summary()

    def add_violation(self, violation: Violation) -> None:
        """Add a browser violation."""
        if self.paused:
            return

        record = {
            "kind": "violation",
            "level": ConsoleLevel.WARNING,
            "level_label": "VIO",
            "text": violation.description,
            "source": _format_source(violation.url, None),
            "timestamp": _format_timestamp(violation.timestamp),
            "full_url": violation.url,
            "line": None,
            "col": None,
            "stack": None,
        }
        self._entries.append(record)
        self._counts["violation"] += 1
        self._counts["warning"] += 1

        if self._matches_filter(record):
            self._add_row(record, len(self._entries) - 1)
        self._update_summary()

    # ── Internal ──

    def _matches_filter(self, record: dict) -> bool:
        # level filter
        allowed = _FILTER_TO_LEVELS.get(self.active_filter)
        if allowed is not None and record["level"] not in allowed:
            # exceptions show under Errors filter
            if record["kind"] == "exception" and ConsoleLevel.ERROR in allowed:
                pass
            elif record["kind"] == "violation" and ConsoleLevel.WARNING in allowed:
                pass
            else:
                return False

        # text search
        if self.search_query and self.search_query.lower() not in record["text"].lower():
            return False

        return True

    def _add_row(self, record: dict, index: int) -> None:
        _, style = _LEVEL_STYLES.get(record["level"], ("LOG", "dim"))

        # special styling for different entry kinds
        if record["kind"] == "exception":
            style = "bold red"
        elif record["kind"] == "violation":
            style = "italic yellow"
        elif record["kind"] == "eval_input":
            style = "bold cyan"
        elif record["kind"] == "eval_result":
            style = "bold green"
        elif record["kind"] == "eval_error":
            style = "bold red"

        level_text = Text(record["level_label"], style=style)
        msg = record["text"]
        # for multiline eval results, show first line only in table
        if "\n" in msg:
            first_line = msg.split("\n", 1)[0]
            msg = first_line + " ..."
        if len(msg) > 120:
            msg = msg[:117] + "..."

        table = self.query_one("#console-table", DataTable)
        table.add_row(
            record["timestamp"],
            level_text,
            msg,
            record["source"],
            key=str(index),
        )
        # auto-scroll to the bottom
        table.scroll_end(animate=False)

    def _rebuild_table(self) -> None:
        table = self.query_one("#console-table", DataTable)
        table.clear()
        for i, record in enumerate(self._entries):
            if self._matches_filter(record):
                self._add_row(record, i)

    def _update_summary(self) -> None:
        try:
            total = len(self._entries)
            self.query_one("#csum-total", Label).update(f"{total} messages")
            self.query_one("#csum-errors", Label).update(f"{self._counts['error']} errors")
            self.query_one("#csum-warnings", Label).update(f"{self._counts['warning']} warnings")
            self.query_one("#csum-exceptions", Label).update(f"{self._counts['exception']} exceptions")
        except NoMatches:
            pass

    def _show_detail(self, record: dict) -> None:
        self.selected_row_data = record
        try:
            panel = self.query_one("#console-detail")
            panel.add_class("visible")
        except NoMatches:
            pass

        content = self.query_one("#console-detail-content", Static)
        lines = []

        if record["kind"] == "exception":
            lines.append(f"[bold red]EXCEPTION[/bold red]  {record.get('description', '')}")
            lines.append("")
            lines.append(f"[bold]{record['text']}[/bold]")
            if record.get("stack"):
                lines.append("")
                lines.append("[dim]Stack Trace:[/dim]")
                lines.append(f"[dim]{record['stack']}[/dim]")
        elif record["kind"] == "violation":
            lines.append(f"[bold yellow]VIOLATION[/bold yellow]")
            lines.append("")
            lines.append(record["text"])
        elif record["kind"] == "eval_input":
            lines.append(f"[bold cyan]> {record['text']}[/bold cyan]")
        elif record["kind"] in ("eval_result", "eval_error"):
            is_error = record["kind"] == "eval_error"
            tag = "[bold red]Error[/bold red]" if is_error else "[bold green]Result[/bold green]"
            lines.append(f"{tag}")
            if record.get("eval_expression"):
                lines.append(f"[dim]Expression:[/dim] [cyan]{record['eval_expression']}[/cyan]")
            if record.get("eval_type"):
                type_info = record["eval_type"]
                if record.get("eval_subtype"):
                    type_info += f" ({record['eval_subtype']})"
                if record.get("eval_class"):
                    type_info += f" [{record['eval_class']}]"
                lines.append(f"[dim]Type:[/dim] {type_info}")
            lines.append("")
            # show full value (not truncated)
            full = record.get("eval_full_value", record["text"])
            if is_error:
                lines.append(f"[red]{full}[/red]")
            else:
                lines.append(full)
            if record.get("stack"):
                lines.append("")
                lines.append("[dim]Stack:[/dim]")
                lines.append(f"[dim]{record['stack']}[/dim]")
        else:
            _, style = _LEVEL_STYLES.get(record["level"], ("LOG", "dim"))
            lines.append(f"[{style}]{record['level_label']}[/{style}]  {record['text']}")

        if record.get("full_url"):
            lines.append("")
            loc = record["full_url"]
            if record.get("line") is not None:
                loc += f":{record['line']}"
                if record.get("col") is not None:
                    loc += f":{record['col']}"
            lines.append(f"[dim]Source:[/dim] {loc}")

        content.update("\n".join(lines))

    # ── Event handlers ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        try:
            index = int(key)
            if 0 <= index < len(self._entries):
                self._show_detail(self._entries[index])
        except (ValueError, IndexError):
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id == "console-expand-btn":
            self._toggle_editor(expand=True)
            return
        elif btn_id == "console-editor-collapse":
            self._toggle_editor(expand=False)
            return
        elif btn_id == "console-editor-run":
            self._run_editor_code()
            return

        if btn_id.startswith("clevel-"):
            filter_name = btn_id.replace("clevel-", "").capitalize()
            self.active_filter = filter_name
            for btn in self.query("#console-filter-bar Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._rebuild_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "console-search":
            self.search_query = event.value
            self._rebuild_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "console-eval-input":
            expression = event.value.strip()
            if not expression:
                return
            # add to history
            if not self._history or self._history[-1] != expression:
                self._history.append(expression)
            self._history_index = -1
            # clear input
            event.input.value = ""
            # show the expression in the log
            self._add_eval_input(expression)
            # fire the callback
            if self._eval_callback:
                self._eval_callback(expression)

    def on_key(self, event) -> None:
        """Handle keyboard shortcuts for eval input and editor."""
        # ctrl+enter in expanded editor = run code
        if event.key == "ctrl+j" or event.key == "ctrl+enter":
            try:
                editor = self.query_one("#console-editor-textarea", TextArea)
                if editor == self.screen.focused:
                    event.prevent_default()
                    self._run_editor_code()
                    return
            except NoMatches:
                pass

        try:
            eval_input = self.query_one("#console-eval-input", Input)
        except NoMatches:
            return

        if eval_input != self.screen.focused:
            return

        if event.key == "up" and self._history:
            event.prevent_default()
            if self._history_index == -1:
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            eval_input.value = self._history[self._history_index]
            eval_input.cursor_position = len(eval_input.value)
        elif event.key == "down" and self._history:
            event.prevent_default()
            if self._history_index == -1:
                return
            elif self._history_index < len(self._history) - 1:
                self._history_index += 1
                eval_input.value = self._history[self._history_index]
                eval_input.cursor_position = len(eval_input.value)
            else:
                self._history_index = -1
                eval_input.value = ""

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#console-search", Input).focus()
        except NoMatches:
            pass

    def action_focus_search(self) -> None:
        self.action_focus_filter()

    def action_focus_eval(self) -> None:
        """Focus the eval input bar, or the editor if expanded."""
        if self._editor_expanded:
            try:
                self.query_one("#console-editor-textarea", TextArea).focus()
            except NoMatches:
                pass
        else:
            try:
                self.query_one("#console-eval-input", Input).focus()
            except NoMatches:
                pass

    def _toggle_editor(self, expand: bool) -> None:
        """Toggle between single-line input and expanded editor."""
        self._editor_expanded = expand
        try:
            panel = self.query_one("#console-editor-panel")
            input_bar = self.query_one("#console-input-bar")
            if expand:
                # copy current input text to editor
                try:
                    val = self.query_one("#console-eval-input", Input).value
                    editor = self.query_one("#console-editor-textarea", TextArea)
                    if val.strip():
                        editor.load_text(val)
                except Exception:
                    pass
                input_bar.add_class("hidden")
                panel.remove_class("hidden")
                self.query_one("#console-editor-textarea", TextArea).focus()
            else:
                panel.add_class("hidden")
                input_bar.remove_class("hidden")
                self.query_one("#console-eval-input", Input).focus()
        except NoMatches:
            pass

    def _run_editor_code(self) -> None:
        """Execute the code in the expanded editor."""
        try:
            editor = self.query_one("#console-editor-textarea", TextArea)
            expression = editor.text.strip()
            if not expression:
                return
            # add to history
            if not self._history or self._history[-1] != expression:
                self._history.append(expression)
            self._history_index = -1
            # show in log
            self._add_eval_input(expression)
            # fire callback
            if self._eval_callback:
                self._eval_callback(expression)
            # clear editor
            editor.load_text("")
        except NoMatches:
            pass

    def action_clear_console(self) -> None:
        self._entries.clear()
        self._counts = {"error": 0, "warning": 0, "info": 0, "debug": 0, "exception": 0, "violation": 0}
        table = self.query_one("#console-table", DataTable)
        table.clear()
        self._update_summary()
        try:
            self.query_one("#console-detail-content", Static).update("Select a message to view details.")
        except NoMatches:
            pass

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused

    # ── Eval support ──

    def _add_eval_input(self, expression: str) -> None:
        """Add the user's expression to the log as an input marker."""
        record = {
            "kind": "eval_input",
            "level": ConsoleLevel.INFO,
            "level_label": ">>>",
            "text": expression,
            "source": "eval",
            "timestamp": _format_timestamp(_now_ms()),
            "full_url": "",
            "line": None,
            "col": None,
            "stack": None,
        }
        self._entries.append(record)
        if self._matches_filter(record):
            self._add_row(record, len(self._entries) - 1)

    def add_eval_result(self, expression: str, result: dict) -> None:
        """Add an eval result to the console log.

        Args:
            expression: The JS expression that was evaluated.
            result: Dict with keys: type, value, description, subtype, error
        """
        is_error = result.get("error", False)
        value = result.get("description") or result.get("value", "undefined")

        # format the display value
        if isinstance(value, (dict, list)):
            try:
                display = json.dumps(value, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                display = str(value)
        else:
            display = str(value)

        # truncate very long results for the table (full in detail view)
        record = {
            "kind": "eval_result" if not is_error else "eval_error",
            "level": ConsoleLevel.ERROR if is_error else ConsoleLevel.INFO,
            "level_label": "ERR" if is_error else "<<<",
            "text": display,
            "source": "eval",
            "timestamp": _format_timestamp(_now_ms()),
            "full_url": "",
            "line": None,
            "col": None,
            "stack": result.get("stack", None),
            "eval_expression": expression,
            "eval_type": result.get("type", ""),
            "eval_subtype": result.get("subtype", ""),
            "eval_class": result.get("className", ""),
            "eval_full_value": display,
        }
        self._entries.append(record)
        if self._matches_filter(record):
            self._add_row(record, len(self._entries) - 1)
        self._update_summary()
