"""Cookies tab -- full cookie jar viewer with security flag analysis."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

from pagescope.models.cookies import Cookie, CookieJarReport

COOKIE_FILTERS = ["All", "Insecure", "Session", "Third-Party", "Large"]


def _format_expires(expires: float) -> str:
    """Format cookie expiry timestamp."""
    if expires <= 0:
        return "Session"
    try:
        dt = datetime.fromtimestamp(expires)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return str(expires)


def _flag_text(value: bool, label: str) -> Text:
    """Return a colored flag indicator."""
    if value:
        return Text(label, style="green")
    return Text(label, style="dim red")


class CookiesTab(Widget):
    """Cookies tab with full cookie jar, security analysis, and filtering."""

    BINDINGS = [
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("r", "request_rescan", "Re-scan", show=True),
    ]

    active_filter: reactive[str] = reactive("All")
    search_query: reactive[str] = reactive("")
    _scan_pending: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._report: CookieJarReport | None = None
        self._cookies: list[Cookie] = []

    def compose(self) -> ComposeResult:
        # overview
        with Vertical(id="cookies-overview"):
            yield Static("Waiting for cookie data...", id="cookies-stats-display")

        # filter bar
        with Horizontal(id="cookies-filter-bar"):
            for name in COOKIE_FILTERS:
                btn = Button(
                    name,
                    id=f"cookiefilter-{name.lower().replace('-', '')}",
                    classes="active" if name == "All" else "",
                )
                yield btn
            yield Input(placeholder="Search cookies...", id="cookies-search")

        # cookie table
        with Vertical(id="cookies-main"):
            yield DataTable(id="cookies-table")
            with Vertical(id="cookies-detail"):
                yield Static("Select a cookie to view details.", id="cookies-detail-content")

        # summary bar
        with Horizontal(id="cookies-summary"):
            yield Label("No data", id="cksum-total")
            yield Label("", id="cksum-secure")
            yield Label("", id="cksum-httponly")
            yield Label("", id="cksum-samesite")
            yield Label("", id="cksum-issues")

    def on_mount(self) -> None:
        table = self.query_one("#cookies-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Name", "Domain", "Secure", "HttpOnly", "SameSite", "Expires", "Size", "Issues")

    # ── Public API ──

    def load_report(self, report: CookieJarReport) -> None:
        """Load a cookie jar report."""
        self._report = report
        self._cookies = report.cookies
        self._update_overview(report)
        self._rebuild_table()
        self._update_summary(report)

    # ── Overview ──

    def _update_overview(self, report: CookieJarReport) -> None:
        parts = []
        parts.append(f"[bold]{report.total_count}[/bold] cookies")
        parts.append(f"[green]{report.secure_count}[/green] secure")
        parts.append(f"[green]{report.httponly_count}[/green] httpOnly")
        parts.append(f"[green]{report.samesite_count}[/green] sameSite")

        if report.session_count:
            parts.append(f"[yellow]{report.session_count}[/yellow] session")
        if report.third_party_count:
            parts.append(f"[yellow]{report.third_party_count}[/yellow] third-party")
        if report.issues_count:
            parts.append(f"[bold red]{report.issues_count}[/bold red] with issues")

        try:
            self.query_one("#cookies-stats-display", Static).update("  ".join(parts))
        except NoMatches:
            pass

    # ── Table ──

    def _matches_filter(self, cookie: Cookie) -> bool:
        f = self.active_filter
        if f == "Insecure" and not (cookie.missing_secure or cookie.missing_http_only or cookie.missing_same_site):
            return False
        if f == "Session" and not cookie.session:
            return False
        if f == "Third-Party" and not cookie.is_third_party:
            return False
        if f == "Large" and not cookie.value_too_large:
            return False

        if self.search_query:
            q = self.search_query.lower()
            if q not in cookie.name.lower() and q not in cookie.domain.lower():
                return False

        return True

    def _rebuild_table(self) -> None:
        try:
            table = self.query_one("#cookies-table", DataTable)
        except NoMatches:
            return
        table.clear()

        for i, cookie in enumerate(self._cookies):
            if not self._matches_filter(cookie):
                continue
            self._add_row(table, cookie, i)

    def _add_row(self, table: DataTable, cookie: Cookie, index: int) -> None:
        # name (highlight third-party)
        name = cookie.name
        if len(name) > 30:
            name = name[:27] + "..."
        name_style = "yellow" if cookie.is_third_party else ""

        # domain
        domain = cookie.domain
        if len(domain) > 25:
            domain = "..." + domain[-22:]

        # flags
        secure = _flag_text(cookie.secure, "\u2713" if cookie.secure else "\u2717")
        httponly = _flag_text(cookie.http_only, "\u2713" if cookie.http_only else "\u2717")
        samesite = cookie.same_site or "None"
        ss_style = "green" if samesite in ("Strict", "Lax") else "dim red"

        # expires
        expires = _format_expires(cookie.expires)

        # size
        size = f"{cookie.size} B"

        # issues column
        issues = []
        if cookie.missing_secure:
            issues.append("!Secure")
        if cookie.missing_http_only:
            issues.append("!HttpOnly")
        if cookie.missing_same_site:
            issues.append("!SameSite")
        if cookie.value_too_large:
            issues.append("large")
        issues_str = ", ".join(issues)
        issues_style = "bold red" if issues else "green"

        table.add_row(
            Text(name, style=name_style),
            domain,
            secure,
            httponly,
            Text(samesite, style=ss_style),
            expires,
            size,
            Text(issues_str or "\u2713", style=issues_style),
            key=str(index),
        )

    # ── Detail ──

    def _show_detail(self, cookie: Cookie) -> None:
        try:
            panel = self.query_one("#cookies-detail")
            panel.add_class("visible")
            content = self.query_one("#cookies-detail-content", Static)
        except NoMatches:
            return

        lines: list[str] = []
        lines.append(f"[bold]{cookie.name}[/bold]")
        lines.append("")

        # value (truncated for display, could be sensitive)
        val = cookie.value
        if len(val) > 100:
            val = val[:97] + "..."
        lines.append(f"  [dim]Value:[/dim]     {val}")
        lines.append(f"  [dim]Domain:[/dim]    {cookie.domain}")
        lines.append(f"  [dim]Path:[/dim]      {cookie.path}")
        lines.append(f"  [dim]Expires:[/dim]   {_format_expires(cookie.expires)}")
        lines.append(f"  [dim]Size:[/dim]      {cookie.size} bytes")
        lines.append(f"  [dim]Priority:[/dim]  {cookie.priority}")
        if cookie.source_scheme:
            lines.append(f"  [dim]Scheme:[/dim]    {cookie.source_scheme}")
        lines.append("")

        # security flags
        lines.append("[bold]Security Flags[/bold]")
        icon = lambda ok: "[green]\u2713[/green]" if ok else "[red]\u2717[/red]"
        lines.append(f"  {icon(cookie.secure)}  Secure")
        lines.append(f"  {icon(cookie.http_only)}  HttpOnly")
        ss_ok = cookie.same_site in ("Strict", "Lax")
        lines.append(f"  {icon(ss_ok)}  SameSite: {cookie.same_site or 'None'}")

        if cookie.is_third_party:
            lines.append("")
            lines.append("  [yellow]Third-party cookie[/yellow]")

        # issues
        issues = []
        if cookie.missing_secure:
            issues.append("Missing Secure flag -- cookie sent over HTTP")
        if cookie.missing_http_only:
            issues.append("Missing HttpOnly flag -- accessible to JavaScript")
        if cookie.missing_same_site:
            issues.append("Missing/weak SameSite -- vulnerable to CSRF")
        if cookie.value_too_large:
            issues.append(f"Cookie size ({cookie.size}B) exceeds 4KB limit")

        if issues:
            lines.append("")
            lines.append("[bold red]Issues[/bold red]")
            for issue in issues:
                lines.append(f"  [red]\u2717[/red]  {issue}")

        content.update("\n".join(lines))

    # ── Summary ──

    def _update_summary(self, report: CookieJarReport) -> None:
        try:
            self.query_one("#cksum-total", Label).update(f"{report.total_count} cookies")
            self.query_one("#cksum-secure", Label).update(f"{report.secure_count} secure")
            self.query_one("#cksum-httponly", Label).update(f"{report.httponly_count} httpOnly")
            self.query_one("#cksum-samesite", Label).update(f"{report.samesite_count} sameSite")
            self.query_one("#cksum-issues", Label).update(
                f"{report.issues_count} issues" if report.issues_count else "no issues"
            )
        except NoMatches:
            pass

    # ── Event handlers ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        try:
            index = int(key)
            if 0 <= index < len(self._cookies):
                self._show_detail(self._cookies[index])
        except (ValueError, IndexError):
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("cookiefilter-"):
            filter_key = btn_id.replace("cookiefilter-", "")
            for name in COOKIE_FILTERS:
                if name.lower().replace("-", "") == filter_key:
                    self.active_filter = name
                    break
            for btn in self.query("#cookies-filter-bar Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._rebuild_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "cookies-search":
            self.search_query = event.value
            self._rebuild_table()

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#cookies-search", Input).focus()
        except NoMatches:
            pass

    def action_request_rescan(self) -> None:
        self._scan_pending = True
