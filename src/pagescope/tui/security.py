"""Security tab -- TLS overview, mixed content, CSP violations, cookie issues."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

from pagescope.models.forensics import SecurityHeadersReport
from pagescope.models.security import (
    CookieIssue,
    CSPViolation,
    MixedContentIssue,
    SecurityReport,
    TLSInfo,
)

# issue category config: (label, style)
_CATEGORY_STYLES = {
    "mixed_content": ("MIXED", "bold red"),
    "csp_violation": ("CSP", "bold yellow"),
    "cookie": ("COOKIE", "yellow"),
    "insecure_form": ("FORM", "bold red"),
}

# severity for sorting/display
_SEVERITY = {
    "mixed_content": 0,
    "insecure_form": 1,
    "csp_violation": 2,
    "cookie": 3,
}

CATEGORY_FILTERS = ["All", "Mixed Content", "CSP", "Cookies", "Forms"]

_FILTER_TO_CATEGORIES = {
    "All": None,
    "Mixed Content": {"mixed_content"},
    "CSP": {"csp_violation"},
    "Cookies": {"cookie"},
    "Forms": {"insecure_form"},
}


def _state_display(state: str) -> tuple[str, str]:
    """Return (display text, rich style) for a security state."""
    mapping = {
        "secure": ("SECURE", "bold green"),
        "neutral": ("NEUTRAL", "bold yellow"),
        "insecure": ("INSECURE", "bold red"),
        "unknown": ("UNKNOWN", "dim"),
    }
    return mapping.get(state, ("UNKNOWN", "dim"))


def _truncate(s: str, max_len: int = 80) -> str:
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


class SecurityTab(Widget):
    """Security tab with TLS overview, issues table, and detail panel."""

    BINDINGS = [
        Binding("f", "focus_filter", "Filter", show=True),
        Binding("r", "refresh_scan", "Rescan", show=True),
    ]

    active_filter: reactive[str] = reactive("All")
    search_query: reactive[str] = reactive("")
    selected_issue: reactive[Any] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._issues: list[dict] = []
        self._tls_info: TLSInfo | None = None
        self._security_state: str = "unknown"
        self._report: SecurityReport | None = None
        self._counts = {
            "mixed_content": 0,
            "csp_violation": 0,
            "cookie": 0,
            "insecure_form": 0,
        }
        self._scan_pending = False
        self._detail_view: str = "issues"  # "issues", "certificate", or "headers"
        self._headers_report: SecurityHeadersReport | None = None

    def compose(self) -> ComposeResult:
        # TLS overview panel
        with Vertical(id="security-overview"):
            yield Static("Waiting for security scan...", id="security-state-display")
            yield Static("", id="tls-summary")

        # view tabs: Issues | Certificate | Headers
        with Horizontal(id="security-view-tabs"):
            yield Button("Issues", id="secview-issues", classes="active")
            yield Button("Certificate", id="secview-certificate")
            yield Button("Headers", id="secview-headers")

        # filter bar (issues view)
        with Horizontal(id="security-filter-bar"):
            for name in CATEGORY_FILTERS:
                btn = Button(
                    name,
                    id=f"secfilter-{name.lower().replace(' ', '-')}",
                    classes="active" if name == "All" else "",
                )
                yield btn
            yield Input(placeholder="Search issues...", id="security-search")

        # issues table + detail
        with Vertical(id="security-main"):
            yield DataTable(id="security-table")
            with Vertical(id="security-detail"):
                yield Static(
                    "Select an issue to view details.", id="security-detail-content"
                )

        # certificate detail view (hidden by default)
        with Vertical(id="security-cert-view", classes="hidden"):
            yield Static("No certificate data available.", id="cert-detail-content")

        # headers scorecard view (hidden by default)
        with Vertical(id="security-headers-view", classes="hidden"):
            yield Static("Waiting for headers analysis...", id="headers-scorecard-content")

        # summary bar
        with Horizontal(id="security-summary"):
            yield Label("No scan yet", id="secsum-state")
            yield Label("0 issues", id="secsum-total")
            yield Label("0 mixed content", id="secsum-mixed")
            yield Label("0 CSP", id="secsum-csp")
            yield Label("0 cookies", id="secsum-cookies")

    def on_mount(self) -> None:
        table = self.query_one("#security-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Sev", "Category", "Description", "Resource")

    # ── Public API ──

    def load_report(self, report: SecurityReport) -> None:
        """Load a full security report into the tab."""
        self._report = report
        self._tls_info = report.tls_info
        self._security_state = report.summary.security_state
        self._issues.clear()
        self._counts = {
            "mixed_content": 0,
            "csp_violation": 0,
            "cookie": 0,
            "insecure_form": 0,
        }

        # convert all issues into unified records
        for mc in report.mixed_content:
            self._issues.append(
                {
                    "category": "mixed_content",
                    "description": f"HTTP resource loaded: {mc.resource_type or 'unknown'}",
                    "resource": mc.url,
                    "resolution": mc.resolution_status,
                    "detail_obj": mc,
                }
            )
            self._counts["mixed_content"] += 1

        for csp in report.csp_violations:
            self._issues.append(
                {
                    "category": "csp_violation",
                    "description": f"Blocked by {csp.violated_directive or csp.effective_directive}",
                    "resource": csp.blocked_url,
                    "source_file": csp.source_file,
                    "line": csp.line_number,
                    "col": csp.column_number,
                    "policy": csp.original_policy,
                    "detail_obj": csp,
                }
            )
            self._counts["csp_violation"] += 1

        for cookie in report.cookie_issues:
            self._issues.append(
                {
                    "category": "cookie",
                    "description": f"{cookie.issue}",
                    "resource": f"{cookie.name} ({cookie.domain})" if cookie.domain else cookie.name,
                    "detail_obj": cookie,
                }
            )
            self._counts["cookie"] += 1

        for form in report.insecure_forms:
            action = form.get("action", "")
            method = form.get("method", "GET").upper()
            has_pw = form.get("has_password", False)
            desc = f"{method} form submits to HTTP"
            if has_pw:
                desc += " (contains password field!)"
            self._issues.append(
                {
                    "category": "insecure_form",
                    "description": desc,
                    "resource": action,
                    "detail_obj": form,
                }
            )
            self._counts["insecure_form"] += 1

        # sort by severity
        self._issues.sort(key=lambda r: _SEVERITY.get(r["category"], 99))

        self._update_overview()
        self._rebuild_table()
        self._update_summary()

    def add_event(self, event_type: str, detail: str) -> None:
        """Add a real-time security event (before full report is ready)."""
        label, _ = _CATEGORY_STYLES.get(event_type, ("???", "dim"))
        record = {
            "category": event_type,
            "description": detail,
            "resource": detail,
            "detail_obj": None,
        }
        self._issues.append(record)
        self._counts[event_type] = self._counts.get(event_type, 0) + 1

        if self._matches_filter(record):
            self._add_row(record, len(self._issues) - 1)
        self._update_summary()

    # ── Internal ──

    def _update_overview(self) -> None:
        """Update the TLS overview panel."""
        state_text, state_style = _state_display(self._security_state)

        try:
            state_display = self.query_one("#security-state-display", Static)
            state_display.update(
                f"[{state_style}]{state_text}[/{state_style}]"
            )
        except NoMatches:
            pass

        tls = self._tls_info
        if tls and tls.protocol:
            lines = []
            lines.append(
                f"[bold]Certificate:[/bold] {tls.certificate_subject}"
            )
            lines.append(f"[dim]Issuer:[/dim] {tls.certificate_issuer}")
            lines.append(
                f"[dim]Protocol:[/dim] {tls.protocol}  [dim]Cipher:[/dim] {tls.cipher}"
            )
            if tls.certificate_valid_to:
                lines.append(
                    f"[dim]Valid:[/dim] {tls.certificate_valid_from} -- {tls.certificate_valid_to}"
                )
            if tls.san_list:
                sans = ", ".join(tls.san_list[:5])
                if len(tls.san_list) > 5:
                    sans += f" (+{len(tls.san_list) - 5} more)"
                lines.append(f"[dim]SANs:[/dim] {sans}")
            try:
                self.query_one("#tls-summary", Static).update("\n".join(lines))
            except NoMatches:
                pass
        else:
            try:
                self.query_one("#tls-summary", Static).update(
                    "[dim]No TLS certificate information available.[/dim]"
                )
            except NoMatches:
                pass

    def _matches_filter(self, record: dict) -> bool:
        allowed = _FILTER_TO_CATEGORIES.get(self.active_filter)
        if allowed is not None and record["category"] not in allowed:
            return False
        if self.search_query:
            q = self.search_query.lower()
            if (
                q not in record.get("description", "").lower()
                and q not in record.get("resource", "").lower()
            ):
                return False
        return True

    def _add_row(self, record: dict, index: int) -> None:
        label, style = _CATEGORY_STYLES.get(record["category"], ("???", "dim"))

        # severity indicator
        sev_map = {
            "mixed_content": Text("!!", style="bold red"),
            "insecure_form": Text("!!", style="bold red"),
            "csp_violation": Text("!", style="yellow"),
            "cookie": Text("~", style="dim yellow"),
        }
        sev = sev_map.get(record["category"], Text("?", style="dim"))
        cat_text = Text(label, style=style)

        table = self.query_one("#security-table", DataTable)
        table.add_row(
            sev,
            cat_text,
            _truncate(record["description"], 60),
            _truncate(record["resource"], 60),
            key=str(index),
        )

    def _rebuild_table(self) -> None:
        table = self.query_one("#security-table", DataTable)
        table.clear()
        for i, record in enumerate(self._issues):
            if self._matches_filter(record):
                self._add_row(record, i)

    def _update_summary(self) -> None:
        total = len(self._issues)
        state_text, _ = _state_display(self._security_state)
        try:
            self.query_one("#secsum-state", Label).update(state_text)
            self.query_one("#secsum-total", Label).update(f"{total} issues")
            self.query_one("#secsum-mixed", Label).update(
                f"{self._counts['mixed_content']} mixed content"
            )
            self.query_one("#secsum-csp", Label).update(
                f"{self._counts['csp_violation']} CSP"
            )
            self.query_one("#secsum-cookies", Label).update(
                f"{self._counts['cookie']} cookies"
            )
        except NoMatches:
            pass

    def _show_detail(self, record: dict) -> None:
        self.selected_issue = record
        try:
            panel = self.query_one("#security-detail")
            panel.add_class("visible")
        except NoMatches:
            pass

        try:
            content = self.query_one("#security-detail-content", Static)
        except NoMatches:
            return
        lines = []
        cat = record["category"]
        label, style = _CATEGORY_STYLES.get(cat, ("???", "dim"))

        lines.append(f"[{style}]{label}[/{style}]  {record['description']}")
        lines.append("")

        obj = record.get("detail_obj")

        if cat == "mixed_content" and isinstance(obj, MixedContentIssue):
            lines.append(f"[bold]URL:[/bold] {obj.url}")
            lines.append(f"[dim]Resource Type:[/dim] {obj.resource_type}")
            lines.append(f"[dim]Status:[/dim] {obj.resolution_status}")

        elif cat == "csp_violation" and isinstance(obj, CSPViolation):
            lines.append(f"[bold]Blocked URL:[/bold] {obj.blocked_url}")
            lines.append(f"[dim]Violated Directive:[/dim] {obj.violated_directive}")
            lines.append(f"[dim]Effective Directive:[/dim] {obj.effective_directive}")
            if obj.source_file:
                loc = obj.source_file
                if obj.line_number is not None:
                    loc += f":{obj.line_number}"
                    if obj.column_number is not None:
                        loc += f":{obj.column_number}"
                lines.append(f"[dim]Source:[/dim] {loc}")
            if obj.original_policy:
                lines.append("")
                lines.append("[dim]Policy:[/dim]")
                # wrap long policy for readability
                policy = obj.original_policy
                if len(policy) > 120:
                    policy = policy[:120] + "..."
                lines.append(f"  {policy}")

        elif cat == "cookie" and isinstance(obj, CookieIssue):
            lines.append(f"[bold]Cookie:[/bold] {obj.name}")
            lines.append(f"[dim]Domain:[/dim] {obj.domain}")
            lines.append(f"[dim]Issue:[/dim] {obj.issue}")

        elif cat == "insecure_form" and isinstance(obj, dict):
            lines.append(f"[bold]Action:[/bold] {obj.get('action', '')}")
            lines.append(f"[dim]Method:[/dim] {obj.get('method', 'GET')}")
            has_pw = obj.get("has_password", False)
            if has_pw:
                lines.append("[bold red]Contains password input field![/bold red]")

        else:
            lines.append(f"[dim]Resource:[/dim] {record.get('resource', '')}")

        content.update("\n".join(lines))

    # ── Event handlers ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        try:
            index = int(key)
            if 0 <= index < len(self._issues):
                self._show_detail(self._issues[index])
        except (ValueError, IndexError):
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        # view tabs: Issues / Certificate
        if btn_id.startswith("secview-"):
            view = btn_id.replace("secview-", "")
            self._detail_view = view
            for btn in self.query("#security-view-tabs Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._switch_view(view)
            return

        if btn_id.startswith("secfilter-"):
            filter_key = btn_id.replace("secfilter-", "")
            # Map back to proper name
            for name in CATEGORY_FILTERS:
                if name.lower().replace(" ", "-") == filter_key:
                    self.active_filter = name
                    break
            for btn in self.query("#security-filter-bar Button"):
                btn.remove_class("active")
            event.button.add_class("active")
            self._rebuild_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "security-search":
            self.search_query = event.value
            self._rebuild_table()

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#security-search", Input).focus()
        except NoMatches:
            pass

    def action_refresh_scan(self) -> None:
        """Request a rescan -- handled by the parent app."""
        self._scan_pending = True

    def load_headers_report(self, report: SecurityHeadersReport) -> None:
        """Load a security headers scorecard."""
        self._headers_report = report
        if self._detail_view == "headers":
            self._render_headers()

    def _switch_view(self, view: str) -> None:
        """Switch between Issues, Certificate, and Headers views."""
        try:
            issues_main = self.query_one("#security-main")
            issues_filter = self.query_one("#security-filter-bar")
            cert_view = self.query_one("#security-cert-view")
            headers_view = self.query_one("#security-headers-view")

            # hide all
            issues_main.add_class("hidden")
            issues_filter.add_class("hidden")
            cert_view.add_class("hidden")
            headers_view.add_class("hidden")

            if view == "certificate":
                cert_view.remove_class("hidden")
                self._render_certificate()
            elif view == "headers":
                headers_view.remove_class("hidden")
                self._render_headers()
            else:
                issues_main.remove_class("hidden")
                issues_filter.remove_class("hidden")
        except NoMatches:
            pass

    def _render_headers(self) -> None:
        """Render the security headers scorecard."""
        try:
            content = self.query_one("#headers-scorecard-content", Static)
        except NoMatches:
            return

        if not self._headers_report:
            content.update("[dim]No headers data. Navigate to a page to analyze response headers.[/dim]")
            return

        r = self._headers_report
        lines: list[str] = []

        # grade display
        grade_colors = {"A+": "bold green", "A": "green", "B": "yellow", "C": "yellow", "D": "bold yellow", "F": "bold red"}
        grade_style = grade_colors.get(r.grade, "bold red")
        lines.append(f"[bold]Security Headers Scorecard[/bold]")
        lines.append("")
        lines.append(f"  Grade: [{grade_style}]{r.grade}[/{grade_style}]  Score: [{grade_style}]{r.score}/100[/{grade_style}]")
        lines.append("")

        if r.missing_critical:
            lines.append(f"  [bold red]Missing critical headers: {', '.join(r.missing_critical)}[/bold red]")
            lines.append("")

        lines.append("[dim]" + "\u2500" * 60 + "[/dim]")
        lines.append("")

        for h in r.headers:
            if h.grade == "good":
                icon = "[green]\u2713[/green]"
            elif h.grade == "warning":
                icon = "[yellow]~[/yellow]"
            elif h.grade == "bad":
                icon = "[red]\u2717[/red]"
            else:
                icon = "[dim]i[/dim]"

            present_str = f"[dim]{h.value[:60]}[/dim]" if h.present else "[dim]not set[/dim]"
            lines.append(f"  {icon}  [bold]{h.name}[/bold]")
            lines.append(f"     {present_str}")
            if h.recommendation:
                lines.append(f"     [yellow]{h.recommendation}[/yellow]")
            lines.append("")

        content.update("\n".join(lines))

    def _render_certificate(self) -> None:
        """Render full X.509 certificate details."""
        try:
            content = self.query_one("#cert-detail-content", Static)
        except NoMatches:
            return

        tls = self._tls_info
        if not tls or not tls.certificate:
            content.update("[dim]No certificate data available. Site may be HTTP or scan hasn't completed.[/dim]")
            return

        cert = tls.certificate
        lines = []

        # header
        lines.append("[bold cyan]Certificate Details[/bold cyan]")
        lines.append("[dim]" + "─" * 60 + "[/dim]")
        lines.append("")

        # subject
        lines.append("[bold]Subject[/bold]")
        if cert.subject_cn:
            lines.append(f"  [dim]Common Name (CN):[/dim]  {cert.subject_cn}")
        if cert.subject_org:
            lines.append(f"  [dim]Organization (O):[/dim]  {cert.subject_org}")
        if cert.subject_ou:
            lines.append(f"  [dim]Org Unit (OU):[/dim]     {cert.subject_ou}")
        if cert.subject_country:
            lines.append(f"  [dim]Country (C):[/dim]       {cert.subject_country}")
        if cert.subject_state:
            lines.append(f"  [dim]State (ST):[/dim]        {cert.subject_state}")
        if cert.subject_locality:
            lines.append(f"  [dim]Locality (L):[/dim]      {cert.subject_locality}")
        lines.append("")

        # issuer
        lines.append("[bold]Issuer[/bold]")
        if cert.issuer_cn:
            lines.append(f"  [dim]Common Name (CN):[/dim]  {cert.issuer_cn}")
        if cert.issuer_org:
            lines.append(f"  [dim]Organization (O):[/dim]  {cert.issuer_org}")
        if cert.issuer_country:
            lines.append(f"  [dim]Country (C):[/dim]       {cert.issuer_country}")
        lines.append("")

        # validity
        lines.append("[bold]Validity[/bold]")
        lines.append(f"  [dim]Not Before:[/dim]  {cert.not_before}")
        lines.append(f"  [dim]Not After:[/dim]   {cert.not_after}")
        if cert.is_expired:
            lines.append("  [bold red]EXPIRED[/bold red]")
        elif cert.days_remaining is not None:
            if cert.days_remaining < 30:
                lines.append(f"  [yellow]Expires in {cert.days_remaining} days[/yellow]")
            else:
                lines.append(f"  [green]{cert.days_remaining} days remaining[/green]")
        lines.append("")

        # serial / Version
        lines.append("[bold]Certificate Info[/bold]")
        if cert.version is not None:
            lines.append(f"  [dim]Version:[/dim]           {cert.version}")
        if cert.serial_number:
            serial = cert.serial_number
            # format serial with colons for readability
            if len(serial) > 8:
                serial = ":".join(serial[i:i+2] for i in range(0, len(serial), 2))
            lines.append(f"  [dim]Serial Number:[/dim]     {serial}")
        if cert.signature_algorithm:
            lines.append(f"  [dim]Signature Algo:[/dim]    {cert.signature_algorithm}")
        if cert.public_key_bits:
            lines.append(f"  [dim]Key Size:[/dim]          {cert.public_key_bits} bits")
        lines.append("")

        # sANs
        if cert.san_list:
            lines.append("[bold]Subject Alternative Names[/bold]")
            for san in cert.san_list:
                lines.append(f"  [cyan]{san}[/cyan]")
            lines.append("")

        # fingerprints
        if cert.sha256_fingerprint or cert.sha1_fingerprint:
            lines.append("[bold]Fingerprints[/bold]")
            if cert.sha256_fingerprint:
                fp = cert.sha256_fingerprint
                fp_formatted = ":".join(fp[i:i+2] for i in range(0, len(fp), 2))
                lines.append(f"  [dim]SHA-256:[/dim]")
                lines.append(f"    {fp_formatted}")
            if cert.sha1_fingerprint:
                fp = cert.sha1_fingerprint
                fp_formatted = ":".join(fp[i:i+2] for i in range(0, len(fp), 2))
                lines.append(f"  [dim]SHA-1:[/dim]")
                lines.append(f"    {fp_formatted}")
            lines.append("")

        # oCSP / CRL
        if cert.ocsp_urls or cert.crl_urls or cert.ca_issuers:
            lines.append("[bold]Authority Information[/bold]")
            for url in cert.ocsp_urls:
                lines.append(f"  [dim]OCSP:[/dim]      {url}")
            for url in cert.ca_issuers:
                lines.append(f"  [dim]CA Issuer:[/dim] {url}")
            for url in cert.crl_urls:
                lines.append(f"  [dim]CRL:[/dim]       {url}")
            lines.append("")

        # connection info from TLSInfo
        lines.append("[bold]Connection[/bold]")
        if tls.protocol:
            lines.append(f"  [dim]Protocol:[/dim]   {tls.protocol}")
        if tls.cipher:
            lines.append(f"  [dim]Cipher:[/dim]     {tls.cipher}")
        if tls.key_exchange:
            lines.append(f"  [dim]Key Exch:[/dim]   {tls.key_exchange}")

        content.update("\n".join(lines))
