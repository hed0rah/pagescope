"""Output formatters for CLI diagnostic reports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class OutputFormat(str, Enum):
    JSON = "json"
    RICH = "rich"


def format_output(report: BaseModel, fmt: OutputFormat, console: Console) -> None:
    """Route report to the appropriate formatter."""
    if fmt == OutputFormat.JSON:
        _render_json(report, console)
    elif fmt == OutputFormat.RICH:
        _render_rich(report, console)


def _render_json(report: BaseModel, console: Console) -> None:
    console.print_json(report.model_dump_json(indent=2))


def _render_rich(report: BaseModel, console: Console) -> None:
    """Render a diagnostic report with Rich formatting."""
    data = report.model_dump()

    # if it's a crawl report with page_results
    if "page_results" in data:
        _render_crawl_report(data, console)
    # if it's a full DiagnosticReport with flows/findings
    elif "flows" in data:
        _render_diagnostic_report(data, console)
    elif "requests" in data:
        _render_network_report(data, console)
    elif "web_vitals" in data:
        _render_performance_report(data, console)
    elif "entries" in data:
        _render_console_report(data, console)
    else:
        # fallback to JSON
        _render_json(report, console)


def _render_diagnostic_report(data: dict, console: Console) -> None:
    url = data.get("url", "")
    console.print(Panel(f"[bold]Diagnostic Report: {url}[/bold]"))

    # findings
    findings = data.get("findings", [])
    if findings:
        table = Table(title="Findings", show_lines=True)
        table.add_column("Severity", style="bold", width=10)
        table.add_column("Category", width=12)
        table.add_column("Title")
        table.add_column("Description")

        severity_styles = {
            "critical": "bold red",
            "error": "red",
            "warning": "yellow",
            "info": "blue",
        }

        for f in findings:
            sev = f.get("severity", "info")
            style = severity_styles.get(sev, "white")
            table.add_row(
                Text(sev.upper(), style=style),
                f.get("category", ""),
                f.get("title", ""),
                f.get("description", ""),
            )
        console.print(table)
    else:
        console.print("[green]No issues found.[/green]")

    # recommendations
    recs = data.get("recommendations", [])
    if recs:
        console.print("\n[bold]Recommendations:[/bold]")
        for i, r in enumerate(recs, 1):
            console.print(f"  {i}. {r}")

    # flow summary
    flows = data.get("flows", [])
    if flows:
        console.print("\n[dim]Modules run:[/dim]", end=" ")
        parts = []
        for f in flows:
            status_icon = "[green]OK[/green]" if f["status"] == "completed" else "[red]ERR[/red]"
            dur = f.get("duration_ms")
            dur_str = f" ({dur:.0f}ms)" if dur else ""
            parts.append(f"{f['module']}: {status_icon}{dur_str}")
        console.print(" | ".join(parts))


def _render_network_report(data: dict, console: Console) -> None:
    summary = data.get("summary", {})
    console.print(
        Panel(
            f"[bold]Network Analysis[/bold]\n"
            f"Total requests: {summary.get('total_requests', 0)} | "
            f"Failed: {summary.get('failed_requests', 0)} | "
            f"Transfer: {summary.get('total_transfer_bytes', 0) / 1024:.1f} KB\n"
            f"Median: {summary.get('median_response_ms') or '?'}ms | "
            f"P95: {summary.get('p95_response_ms') or '?'}ms"
        )
    )

    # failed requests
    failed = data.get("failed_requests", [])
    if failed:
        table = Table(title="Failed Requests")
        table.add_column("Status", width=8)
        table.add_column("URL")
        table.add_column("Error")
        for r in failed[:10]:
            table.add_row(
                str(r.get("status", 0)),
                r.get("url", "")[:80],
                r.get("failure", "") or "",
            )
        console.print(table)

    # slow requests
    slow = data.get("slow_requests", [])
    if slow:
        table = Table(title="Slow Requests")
        table.add_column("Duration", width=10)
        table.add_column("Type", width=12)
        table.add_column("URL")
        for r in slow[:10]:
            table.add_row(
                f"{r.get('duration_ms', 0):.0f}ms",
                r.get("resource_type", ""),
                r.get("url", "")[:80],
            )
        console.print(table)


def _render_performance_report(data: dict, console: Console) -> None:
    vitals = data.get("web_vitals", {})

    def _vital_str(name: str, value: float | None, unit: str, good: float, poor: float) -> str:
        if value is None:
            return f"{name}: [dim]N/A[/dim]"
        if unit == "ms":
            formatted = f"{value:.0f}ms"
        else:
            formatted = f"{value:.3f}"
        if value <= good:
            return f"{name}: [green]{formatted}[/green]"
        elif value <= poor:
            return f"{name}: [yellow]{formatted}[/yellow]"
        else:
            return f"{name}: [red]{formatted}[/red]"

    lines = [
        "[bold]Core Web Vitals[/bold]",
        _vital_str("LCP", vitals.get("lcp_ms"), "ms", 2500, 4000),
        _vital_str("FCP", vitals.get("fcp_ms"), "ms", 1800, 3000),
        _vital_str("CLS", vitals.get("cls"), "", 0.1, 0.25),
        _vital_str("TTFB", vitals.get("ttfb_ms"), "ms", 800, 1800),
    ]
    console.print(Panel("\n".join(lines)))

    recs = data.get("recommendations", [])
    if recs:
        console.print("[bold]Recommendations:[/bold]")
        for i, r in enumerate(recs, 1):
            console.print(f"  {i}. {r}")


def _render_console_report(data: dict, console: Console) -> None:
    summary = data.get("summary", {})
    console.print(
        Panel(
            f"[bold]Console Report[/bold]\n"
            f"Messages: {summary.get('total_messages', 0)} | "
            f"Errors: {summary.get('errors', 0)} | "
            f"Warnings: {summary.get('warnings', 0)} | "
            f"Exceptions: {summary.get('exceptions', 0)}"
        )
    )

    exceptions = data.get("exceptions", [])
    if exceptions:
        console.print("\n[bold red]Unhandled Exceptions:[/bold red]")
        for exc in exceptions[:5]:
            console.print(f"  [red]{exc.get('message', '')}[/red]")
            st = exc.get("stack_trace", "")
            if st:
                for line in st.split("\n")[:3]:
                    console.print(f"    [dim]{line}[/dim]")

    entries = data.get("entries", [])
    errors = [e for e in entries if e.get("level") == "error"]
    if errors:
        console.print(f"\n[bold]Console Errors ({len(errors)}):[/bold]")
        for e in errors[:10]:
            url = e.get("url", "")
            loc = f" ({url}:{e.get('line_number', '?')})" if url else ""
            console.print(f"  [red]{e.get('text', '')[:120]}[/red]{loc}")


def _render_crawl_report(data: dict, console: Console) -> None:
    start_url = data.get("start_url", "")
    pages_crawled = data.get("pages_crawled", 0)
    duration = data.get("crawl_duration_ms")
    duration_str = f" in {duration / 1000:.1f}s" if duration else ""

    console.print(
        Panel(
            f"[bold]Crawl Report: {start_url}[/bold]\n"
            f"Pages crawled: {pages_crawled} | "
            f"Depth: {data.get('max_depth', 0)} | "
            f"Links found: {data.get('total_links_found', 0)}"
            f"{duration_str}"
        )
    )

    # aggregate findings
    findings = data.get("aggregate_findings", [])
    if findings:
        table = Table(title=f"Aggregate Findings ({len(findings)})", show_lines=True)
        table.add_column("Severity", style="bold", width=10)
        table.add_column("Category", width=12)
        table.add_column("Title")
        table.add_column("Page", width=30)

        severity_styles = {
            "critical": "bold red",
            "error": "red",
            "warning": "yellow",
            "info": "blue",
        }

        for f in findings[:30]:  # Cap at 30 for readability
            sev = f.get("severity", "info")
            style = severity_styles.get(sev, "white")
            source = f.get("details", {}).get("source_url", "")
            source_short = source[:28] + "…" if len(source) > 30 else source
            table.add_row(
                Text(sev.upper(), style=style),
                f.get("category", ""),
                f.get("title", ""),
                source_short,
            )
        console.print(table)

        if len(findings) > 30:
            console.print(f"  [dim]... and {len(findings) - 30} more findings[/dim]")
    else:
        console.print("[green]No issues found across any pages.[/green]")

    # recommendations
    recs = data.get("recommendations", [])
    if recs:
        console.print("\n[bold]Recommendations:[/bold]")
        for i, r in enumerate(recs, 1):
            console.print(f"  {i}. {r}")

    # per-page summary
    page_results = data.get("page_results", [])
    if page_results:
        console.print(f"\n[bold]Pages ({len(page_results)}):[/bold]")
        for pr in page_results:
            n_findings = len(pr.get("report", {}).get("findings", []))
            err = pr.get("error")
            if err:
                console.print(f"  [red]✗[/red] [dim]depth {pr.get('depth', 0)}[/dim] {pr.get('url', '')[:70]} [red]({err})[/red]")
            else:
                console.print(
                    f"  [green]✓[/green] [dim]depth {pr.get('depth', 0)}[/dim] "
                    f"{pr.get('url', '')[:70]} "
                    f"[dim]({n_findings} findings, {pr.get('links_found', 0)} links)[/dim]"
                )
