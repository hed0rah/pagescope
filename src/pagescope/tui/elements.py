"""Elements tab -- DOM tree, CSS coverage, layout issues, hidden elements, comments, endpoints."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static, Tree

from pagescope.diagnostics.forensics import _is_interesting
from pagescope.models.dom import DOMReport
from pagescope.models.forensics import ForensicsReport

# self-closing HTML elements (no children, no closing tag)
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


def _build_node_label(node: dict) -> Text | None:
    """Build a Rich Text label for a DOM node, styled like DevTools source view."""
    node_type = node.get("nodeType", 0)
    node_name = node.get("nodeName", "")

    if node_type == 1:  # Element
        tag = node_name.lower()
        attrs = node.get("attributes", [])
        label = Text()
        label.append("<", style="dim")
        label.append(tag, style="bold cyan")

        # attributes come as flat list: [name, value, name, value, ...]
        for i in range(0, len(attrs) - 1, 2):
            attr_name = attrs[i]
            attr_value = attrs[i + 1]
            label.append(" ")
            label.append(attr_name, style="yellow")
            label.append('="', style="dim")
            # truncate long attribute values
            if len(attr_value) > 60:
                attr_value = attr_value[:57] + "..."
            label.append(attr_value, style="green")
            label.append('"', style="dim")

        if tag in _VOID_ELEMENTS:
            label.append(" /", style="dim")
        label.append(">", style="dim")
        return label

    elif node_type == 3:  # Text
        text = (node.get("nodeValue") or "").strip()
        if not text:
            return None  # Skip empty text nodes
        if len(text) > 80:
            text = text[:77] + "..."
        label = Text()
        label.append(f'"{text}"', style="dim")
        return label

    elif node_type == 8:  # Comment
        text = (node.get("nodeValue") or "").strip()
        if not text:
            return None
        if len(text) > 80:
            text = text[:77] + "..."
        label = Text()
        label.append(f"<!-- {text} -->", style="dim green")
        return label

    elif node_type == 10:  # DocumentType
        label = Text()
        label.append(f"<!DOCTYPE {node_name}>", style="dim")
        return label

    elif node_type == 9:  # Document
        return Text("#document", style="bold")

    return None


ELEMENT_VIEWS = ["DOM Tree", "CSS Coverage", "Layout Issues", "Hidden", "Comments", "Endpoints", "Search"]


def _format_bytes(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _issue_severity(issue_type: str) -> tuple[str, str]:
    """Return (indicator, style) for a layout issue type."""
    mapping = {
        "no-dimensions-on-media": ("~", "yellow"),
        "horizontal-overflow": ("!", "bold red"),
        "huge-dom": ("!", "bold yellow"),
        "no-viewport-meta": ("!", "bold yellow"),
        "excessive-inline-styles": ("~", "yellow"),
    }
    return mapping.get(issue_type, ("?", "dim"))


class ElementsTab(Widget):
    """Elements tab with DOM overview, CSS coverage, layout issues, and element search."""

    BINDINGS = [
        Binding("r", "request_rescan", "Re-scan", show=True),
        Binding("slash", "focus_search", "Search", show=True),
    ]

    active_view: reactive[str] = reactive("DOM Tree")
    _scan_pending: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._report: DOMReport | None = None
        self._forensics: ForensicsReport | None = None
        self._search_query: str = ""
        self._search_results: list[dict] = []
        self._search_callback: Any = None  # Set by app for element search
        self._highlight_callback: Any = None  # Set by app: fn(backend_node_id) -> None
        self._dom_tree_data: dict | None = None  # CDP DOM.getDocument result

    def compose(self) -> ComposeResult:
        # DOM stats overview
        with Vertical(id="elements-overview"):
            yield Static("Waiting for DOM analysis...", id="dom-stats-display")

        # view tabs
        with Horizontal(id="elements-view-tabs"):
            for name in ELEMENT_VIEWS:
                btn = Button(
                    name,
                    id=f"eview-{name.lower().replace(' ', '-')}",
                    classes="active" if name == "DOM Tree" else "",
                )
                yield btn

        # search bar (visible in Search view)
        with Horizontal(id="elements-search-bar", classes="hidden"):
            yield Input(
                placeholder="CSS selector (e.g. div.container, #main, a[href])...",
                id="elements-selector-input",
            )

        # DOM Tree view -- summary stats + collapsible source tree
        with Vertical(id="elements-dom-view"):
            yield Static("Waiting for DOM analysis...", id="elements-dom-content")
            yield Tree("DOM", id="dom-tree")

        # CSS Coverage view
        with Vertical(id="elements-css-view", classes="hidden"):
            yield DataTable(id="css-coverage-table")

        # layout Issues view
        with Vertical(id="elements-issues-view", classes="hidden"):
            yield DataTable(id="layout-issues-table")

        # hidden elements view
        with Vertical(id="elements-hidden-view", classes="hidden"):
            yield DataTable(id="hidden-elements-table")

        # comments view
        with Vertical(id="elements-comments-view", classes="hidden"):
            yield Static("Waiting for forensics scan...", id="comments-content")

        # endpoints view
        with Vertical(id="elements-endpoints-view", classes="hidden"):
            yield DataTable(id="endpoints-table")

        # search results view
        with Vertical(id="elements-search-view", classes="hidden"):
            yield DataTable(id="elements-search-table")
            with Vertical(id="elements-search-detail"):
                yield Static("Enter a CSS selector and press Enter to search.", id="elements-search-detail-content")

        # summary bar
        with Horizontal(id="elements-summary"):
            yield Label("No data", id="esum-nodes")
            yield Label("", id="esum-depth")
            yield Label("", id="esum-css")
            yield Label("", id="esum-issues")

    def on_mount(self) -> None:
        # CSS coverage table
        css_table = self.query_one("#css-coverage-table", DataTable)
        css_table.cursor_type = "row"
        css_table.add_columns("Stylesheet", "Total", "Used", "Unused %", "Bar")

        # layout issues table
        issues_table = self.query_one("#layout-issues-table", DataTable)
        issues_table.cursor_type = "row"
        issues_table.add_columns("Sev", "Type", "Selector", "Details")

        # hidden elements table
        hidden_table = self.query_one("#hidden-elements-table", DataTable)
        hidden_table.cursor_type = "row"
        hidden_table.add_columns("Tag", "Reason", "Content", "Links/Forms")

        # endpoints table
        endpoints_table = self.query_one("#endpoints-table", DataTable)
        endpoints_table.cursor_type = "row"
        endpoints_table.add_columns("Source", "Method", "URL", "Context")

        # search results table
        search_table = self.query_one("#elements-search-table", DataTable)
        search_table.cursor_type = "row"
        search_table.add_columns("Tag", "ID", "Classes", "Text Preview", "Attributes")

    # ── Public API ──

    def load_report(self, report: DOMReport) -> None:
        """Load a full DOM report into the tab."""
        self._report = report
        self._update_overview(report)
        self._update_dom_tree(report)
        self._update_css_coverage(report)
        self._update_layout_issues(report)
        self._update_summary(report)

    def load_forensics(self, report: ForensicsReport) -> None:
        """Load forensics analysis results."""
        self._forensics = report
        self._update_hidden_elements(report)
        self._update_comments(report)
        self._update_endpoints(report)
        self._update_summary_with_forensics(report)

    def load_search_results(self, results: list[dict]) -> None:
        """Load element search results from the app."""
        self._search_results = results
        self._update_search_table()

    def load_dom_tree(self, root: dict) -> None:
        """Load a CDP DOM tree (from DOM.getDocument) into the Tree widget."""
        self._dom_tree_data = root
        try:
            tree = self.query_one("#dom-tree", Tree)
        except NoMatches:
            return

        tree.clear()
        tree.root.expand()
        self._node_count = 0
        self._build_tree_node(tree.root, root, depth=0)

    def _build_tree_node(self, parent_tree_node, dom_node: dict, depth: int) -> None:
        """Recursively build tree from CDP DOM data."""
        if self._node_count > 2000 or depth > 50:
            return

        label = _build_node_label(dom_node)
        if label is None:
            # skip nodes with no renderable label (empty text)
            # but still process children for Document nodes
            if dom_node.get("nodeType") == 9:
                for child in dom_node.get("children", []):
                    self._build_tree_node(parent_tree_node, child, depth)
            return

        node_type = dom_node.get("nodeType", 0)
        tag = dom_node.get("nodeName", "").lower()
        children = dom_node.get("children", [])
        backend_id = dom_node.get("backendNodeId", 0)

        # determine if this should be expandable
        is_void = node_type == 1 and tag in _VOID_ELEMENTS
        has_children = bool(children) and not is_void

        if has_children:
            tree_node = parent_tree_node.add(label, data={"backendNodeId": backend_id})
            self._node_count += 1

            # auto-expand first 2 levels (html, head, body)
            if depth < 2:
                tree_node.expand()

            for child in children:
                self._build_tree_node(tree_node, child, depth + 1)
        else:
            tree_node = parent_tree_node.add_leaf(label, data={"backendNodeId": backend_id})
            self._node_count += 1

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """When a tree node is highlighted (cursor moves to it), trigger browser highlight."""
        if self._highlight_callback and event.node.data:
            backend_id = event.node.data.get("backendNodeId", 0)
            if backend_id:
                self._highlight_callback(backend_id)

    # ── View switching ──

    def _switch_view(self, view_name: str) -> None:
        self.active_view = view_name
        view_ids = {
            "DOM Tree": "#elements-dom-view",
            "CSS Coverage": "#elements-css-view",
            "Layout Issues": "#elements-issues-view",
            "Hidden": "#elements-hidden-view",
            "Comments": "#elements-comments-view",
            "Endpoints": "#elements-endpoints-view",
            "Search": "#elements-search-view",
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

        # show/hide search bar
        try:
            search_bar = self.query_one("#elements-search-bar")
            if view_name == "Search":
                search_bar.remove_class("hidden")
            else:
                search_bar.add_class("hidden")
        except NoMatches:
            pass

    # ── Overview ──

    def _update_overview(self, report: DOMReport) -> None:
        s = report.summary
        m = report.size_metrics

        parts = []
        parts.append(f"[bold]{m.total_elements:,}[/bold] elements")
        parts.append(f"[bold]{m.total_nodes:,}[/bold] nodes")
        parts.append(f"depth [bold]{m.max_depth}[/bold]")
        parts.append(f"max children [bold]{m.max_children}[/bold]")

        meta_parts = []
        meta_parts.append(f"{'[green]\u2713[/green]' if s.has_doctype else '[red]\u2717[/red]'} DOCTYPE")
        meta_parts.append(f"{'[green]\u2713[/green]' if s.has_charset else '[red]\u2717[/red]'} charset")
        meta_parts.append(f"{'[green]\u2713[/green]' if s.has_viewport else '[red]\u2717[/red]'} viewport")
        meta_parts.append(f"{s.scripts_count} scripts")
        meta_parts.append(f"{s.stylesheets_count} stylesheets")
        if s.inline_styles_count > 0:
            meta_parts.append(f"{s.inline_styles_count} inline styles")

        text = "  ".join(parts) + "\n" + "  ".join(meta_parts)
        try:
            self.query_one("#dom-stats-display", Static).update(text)
        except NoMatches:
            pass

    # ── DOM Tree view ──

    def _update_dom_tree(self, report: DOMReport) -> None:
        """Render a summary DOM tree view."""
        lines: list[str] = []
        s = report.summary
        m = report.size_metrics

        lines.append("[bold]DOM Structure[/bold]")
        lines.append("")

        # node count assessment
        if m.total_elements > 3000:
            lines.append(f"  [bold red]\u2717  {m.total_elements:,} elements[/bold red] -- very large DOM, will impact performance")
        elif m.total_elements > 1500:
            lines.append(f"  [yellow]~  {m.total_elements:,} elements[/yellow] -- large DOM, consider reducing")
        else:
            lines.append(f"  [green]\u2713  {m.total_elements:,} elements[/green] -- within recommended range")

        # depth assessment
        if m.max_depth > 32:
            lines.append(f"  [bold red]\u2717  Depth: {m.max_depth}[/bold red] -- extremely deep nesting")
        elif m.max_depth > 15:
            lines.append(f"  [yellow]~  Depth: {m.max_depth}[/yellow] -- consider flattening structure")
        else:
            lines.append(f"  [green]\u2713  Depth: {m.max_depth}[/green] -- good")

        # max children
        if m.max_children > 60:
            lines.append(f"  [bold red]\u2717  Max children: {m.max_children}[/bold red] -- consider virtualization")
        elif m.max_children > 30:
            lines.append(f"  [yellow]~  Max children: {m.max_children}[/yellow]")
        else:
            lines.append(f"  [green]\u2713  Max children: {m.max_children}[/green]")

        lines.append("")
        lines.append(f"  Total nodes (incl. text/comment): {m.total_nodes:,}")
        lines.append(f"  Body direct children: {m.body_children}")

        # page metadata
        lines.append("")
        lines.append("[bold]Page Metadata[/bold]")
        lines.append("")
        checks = [
            (s.has_doctype, "DOCTYPE declaration"),
            (s.has_charset, "Character set (charset)"),
            (s.has_viewport, "Viewport meta tag"),
        ]
        for ok, label in checks:
            icon = "[green]\u2713[/green]" if ok else "[red]\u2717[/red]"
            lines.append(f"  {icon}  {label}")

        lines.append("")
        lines.append(f"  Scripts: {s.scripts_count}    Stylesheets: {s.stylesheets_count}    Inline styles: {s.inline_styles_count}")

        # CSS coverage summary
        if report.css_coverage and report.css_coverage.total_bytes > 0:
            cov = report.css_coverage
            lines.append("")
            lines.append("[bold]CSS Coverage[/bold]")
            lines.append("")
            used_pct = 100 - cov.unused_pct
            bar_width = int(used_pct / 100 * 30)
            bar = "[green]" + "\u2588" * bar_width + "[/green]" + "[red]" + "\u2588" * (30 - bar_width) + "[/red]"
            lines.append(f"  {bar}  {used_pct:.1f}% used")
            lines.append(f"  Total: {_format_bytes(cov.total_bytes)}  Used: {_format_bytes(cov.used_bytes)}  Unused: {_format_bytes(cov.total_bytes - cov.used_bytes)}")

        try:
            self.query_one("#elements-dom-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── CSS Coverage table ──

    def _update_css_coverage(self, report: DOMReport) -> None:
        try:
            table = self.query_one("#css-coverage-table", DataTable)
        except NoMatches:
            return
        table.clear()

        cov = report.css_coverage
        if not cov or not cov.entries:
            table.add_row("No CSS coverage data", "", "", "", "")
            return

        for entry in sorted(cov.entries, key=lambda e: e.unused_pct, reverse=True):
            # truncate URL
            url = entry.url
            if len(url) > 40:
                url = "..." + url[-37:]

            bar_width = int((100 - entry.unused_pct) / 100 * 20)

            if entry.unused_pct > 80:
                style = "bold red"
            elif entry.unused_pct > 50:
                style = "yellow"
            else:
                style = "green"

            bar = Text()
            bar.append("\u2591" * bar_width, style=f"{style} on {style}")
            bar.append("\u2591" * (20 - bar_width), style="dim on dim")

            table.add_row(
                url,
                _format_bytes(entry.total_bytes),
                _format_bytes(entry.used_bytes),
                Text(f"{entry.unused_pct:.1f}%", style=style),
                bar,
            )

        # summary row
        table.add_row(
            Text("TOTAL", style="bold"),
            _format_bytes(cov.total_bytes),
            _format_bytes(cov.used_bytes),
            Text(f"{cov.unused_pct:.1f}%", style="bold"),
            "",
        )

    # ── Layout Issues table ──

    def _update_layout_issues(self, report: DOMReport) -> None:
        try:
            table = self.query_one("#layout-issues-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not report.layout_issues:
            table.add_row("", "No issues", "Page looks good!", "")
            return

        for issue in report.layout_issues:
            indicator, style = _issue_severity(issue.issue_type)
            sev = Text(indicator, style=style)

            # friendly type names
            type_names = {
                "no-dimensions-on-media": "Missing Dimensions",
                "horizontal-overflow": "Horizontal Overflow",
                "huge-dom": "Large DOM",
                "no-viewport-meta": "No Viewport",
                "excessive-inline-styles": "Inline Styles",
            }
            type_label = type_names.get(issue.issue_type, issue.issue_type)

            selector = issue.selector
            if len(selector) > 40:
                selector = selector[:37] + "..."

            details = issue.details
            if len(details) > 60:
                details = details[:57] + "..."

            table.add_row(sev, type_label, selector, details)

    # ── Hidden Elements ──

    def _update_hidden_elements(self, report: ForensicsReport) -> None:
        try:
            table = self.query_one("#hidden-elements-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not report.hidden_elements:
            table.add_row("", "No hidden elements found", "", "")
            return

        for el in report.hidden_elements:
            # flags
            flags = []
            if el.has_links:
                flags.append("links")
            if el.has_forms:
                flags.append("forms")
            if el.has_inputs:
                flags.append("inputs")
            flags_str = ", ".join(flags) if flags else ""

            # truncate content
            content = el.text_content
            if len(content) > 60:
                content = content[:57] + "..."

            tag_text = Text(el.selector, style="bold red" if _is_interesting(el.text_content) else "")
            reason_text = Text(el.reason, style="yellow" if el.reason in ("display:none", "input[type=hidden]") else "dim")

            table.add_row(tag_text, reason_text, content, flags_str)

    # ── Comments ──

    def _update_comments(self, report: ForensicsReport) -> None:
        try:
            content_widget = self.query_one("#comments-content", Static)
        except NoMatches:
            return

        if not report.comments:
            content_widget.update("[dim]No HTML comments found on this page.[/dim]")
            return

        lines: list[str] = []
        interesting = [c for c in report.comments if c.interesting]
        normal = [c for c in report.comments if not c.interesting]

        lines.append(f"[bold]{len(report.comments)} comment(s) found[/bold]")
        if interesting:
            lines.append(f"  [bold red]{len(interesting)} contain interesting patterns[/bold red]")
        lines.append("")

        # show interesting comments first
        if interesting:
            lines.append("[bold red]Interesting Comments[/bold red]")
            lines.append("[dim]" + "\u2500" * 50 + "[/dim]")
            for c in interesting:
                lines.append(f"  [dim]({c.location})[/dim]")
                lines.append(f"  [bold red]{c.text}[/bold red]")
                lines.append("")

        if normal:
            lines.append("[bold]Other Comments[/bold]")
            lines.append("[dim]" + "\u2500" * 50 + "[/dim]")
            for c in normal:
                text = c.text
                if len(text) > 200:
                    text = text[:197] + "..."
                lines.append(f"  [dim]({c.location})[/dim] {text}")
                lines.append("")

        content_widget.update("\n".join(lines))

    # ── Endpoints ──

    def _update_endpoints(self, report: ForensicsReport) -> None:
        try:
            table = self.query_one("#endpoints-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not report.endpoints:
            table.add_row("", "", "No endpoints discovered", "")
            return

        # group and sort: external first, then by source type
        for ep in report.endpoints:
            # color by source type
            source_styles = {
                "link": "cyan",
                "form": "yellow",
                "script": "green",
                "image": "dim",
                "stylesheet": "dim",
                "iframe": "bold yellow",
                "meta-refresh": "bold red",
                "meta": "dim",
            }
            style = source_styles.get(ep.source, "")

            url = ep.url
            if len(url) > 80:
                url = url[:77] + "..."

            context = ep.context
            if len(context) > 30:
                context = context[:27] + "..."

            method_style = "bold red" if ep.method == "POST" else ""

            table.add_row(
                Text(ep.source, style=style),
                Text(ep.method, style=method_style),
                url,
                context,
            )

    # ── Summary with forensics ──

    def _update_summary_with_forensics(self, report: ForensicsReport) -> None:
        try:
            if report.hidden_elements:
                self.query_one("#esum-issues", Label).update(
                    f"{len(report.hidden_elements)} hidden"
                )
        except NoMatches:
            pass

    # ── Search ──

    def _update_search_table(self) -> None:
        try:
            table = self.query_one("#elements-search-table", DataTable)
        except NoMatches:
            return
        table.clear()

        if not self._search_results:
            return

        for i, el in enumerate(self._search_results):
            tag = el.get("tag", "")
            el_id = el.get("id", "")
            classes = el.get("classes", "")
            text = el.get("text", "")
            if len(text) > 40:
                text = text[:37] + "..."
            attrs = el.get("attrs_display", "")
            if len(attrs) > 40:
                attrs = attrs[:37] + "..."

            table.add_row(tag, el_id, classes, text, attrs, key=str(i))

        try:
            detail = self.query_one("#elements-search-detail-content", Static)
            detail.update(f"Found {len(self._search_results)} matching elements. Select one for details.")
        except NoMatches:
            pass

    def _show_search_detail(self, el: dict) -> None:
        try:
            panel = self.query_one("#elements-search-detail")
            panel.add_class("visible")
        except NoMatches:
            pass

        lines: list[str] = []
        lines.append(f"[bold]<{el.get('tag', '')}>[/bold]")
        lines.append("")

        if el.get("id"):
            lines.append(f"  [dim]id:[/dim] {el['id']}")
        if el.get("classes"):
            lines.append(f"  [dim]class:[/dim] {el['classes']}")

        attrs = el.get("attributes", {})
        if attrs:
            lines.append("")
            lines.append("[bold]Attributes[/bold]")
            for k, v in attrs.items():
                if k not in ("id", "class"):
                    val = str(v)
                    if len(val) > 80:
                        val = val[:77] + "..."
                    lines.append(f"  [dim]{k}:[/dim] {val}")

        if el.get("text"):
            lines.append("")
            lines.append("[bold]Text Content[/bold]")
            text = el["text"]
            if len(text) > 200:
                text = text[:197] + "..."
            lines.append(f"  {text}")

        if el.get("bbox"):
            bbox = el["bbox"]
            lines.append("")
            lines.append("[bold]Bounding Box[/bold]")
            lines.append(f"  x: {bbox.get('x', 0):.0f}  y: {bbox.get('y', 0):.0f}")
            lines.append(f"  width: {bbox.get('width', 0):.0f}  height: {bbox.get('height', 0):.0f}")

        try:
            self.query_one("#elements-search-detail-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    # ── Summary ──

    def _update_summary(self, report: DOMReport) -> None:
        s = report.summary
        m = report.size_metrics
        try:
            self.query_one("#esum-nodes", Label).update(f"{m.total_elements:,} elements")
            self.query_one("#esum-depth", Label).update(f"depth {m.max_depth}")

            if report.css_coverage and report.css_coverage.total_bytes > 0:
                used_pct = 100 - report.css_coverage.unused_pct
                self.query_one("#esum-css", Label).update(f"CSS {used_pct:.0f}% used")
            else:
                self.query_one("#esum-css", Label).update("")

            n_issues = len(report.layout_issues)
            self.query_one("#esum-issues", Label).update(
                f"{n_issues} issue{'s' if n_issues != 1 else ''}" if n_issues else "no issues"
            )
        except NoMatches:
            pass

    # ── Event handlers ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("eview-"):
            view_key = btn_id.replace("eview-", "").replace("-", " ").title()
            # Map back to exact names
            for v in ELEMENT_VIEWS:
                if v.lower() == view_key.lower():
                    view_key = v
                    break
            self._switch_view(view_key)
            for btn in self.query("#elements-view-tabs Button"):
                btn.remove_class("active")
            event.button.add_class("active")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "elements-selector-input":
            self._search_query = event.value.strip()
            if self._search_query and self._search_callback:
                self._search_callback(self._search_query)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Only handle search table selections
        try:
            table = self.query_one("#elements-search-table", DataTable)
            if event.data_table is not table:
                return
        except NoMatches:
            return

        key = event.row_key.value
        try:
            index = int(key)
            if 0 <= index < len(self._search_results):
                self._show_search_detail(self._search_results[index])
        except (ValueError, IndexError):
            pass

    def action_request_rescan(self) -> None:
        self._scan_pending = True

    def action_focus_search(self) -> None:
        """Switch to search view and focus the input."""
        self._switch_view("Search")
        # update button state
        for btn in self.query("#elements-view-tabs Button"):
            btn.remove_class("active")
        try:
            self.query_one("#eview-search", Button).add_class("active")
        except NoMatches:
            pass
        try:
            self.query_one("#elements-selector-input", Input).focus()
        except NoMatches:
            pass
