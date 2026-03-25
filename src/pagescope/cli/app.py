"""Typer CLI for pagescope -- web diagnostics from the terminal."""

from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from pagescope.cli.formatters import OutputFormat, format_output

app = typer.Typer(
    name="pagescope",
    help="Chrome DevTools in your terminal.",
    no_args_is_help=True,
)
console = Console()


class Format(str, Enum):
    json = "json"
    rich = "rich"
    html = "html"


def _write_output(content: str, output_path: Path | None) -> None:
    """Write content to file or print to console."""
    if output_path:
        output_path.write_text(content, encoding="utf-8")
        console.print(f"[green]Report written to {output_path}[/green]")
    else:
        console.print(content)


@app.command()
def diagnose(
    url: Annotated[str, typer.Argument(help="URL to diagnose")],
    symptom: Annotated[
        Optional[list[str]],
        typer.Option("--symptom", "-s", help="Symptom to investigate (repeatable)"),
    ] = None,
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Write report to file (required for html)")
    ] = None,
    screenshot: Annotated[
        bool, typer.Option("--screenshot", help="Include screenshot")
    ] = False,
) -> None:
    """Run a full diagnostic on a URL."""
    asyncio.run(_diagnose(url, symptom, fmt, output, screenshot))


async def _diagnose(
    url: str,
    symptoms: list[str] | None,
    fmt: Format,
    output: Path | None,
    screenshot: bool,
) -> None:
    from pagescope.orchestrator import Orchestrator, Symptom
    from pagescope.session import DiagnosticSession

    parsed = [Symptom(s) for s in symptoms] if symptoms else None

    console.print(f"[bold]Diagnosing {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        orchestrator = Orchestrator(session)
        report = await orchestrator.diagnose(url=url, symptoms=parsed)

        if screenshot:
            import base64

            data = await session.screenshot()
            report.screenshot_base64 = base64.b64encode(data).decode()

    if fmt == Format.html:
        from pagescope.cli.html_report import render_diagnostic_html

        html_content = render_diagnostic_html(report)
        _write_output(html_content, output or Path("report.html"))
    else:
        format_output(report, OutputFormat(fmt.value), console)


@app.command()
def network(
    url: Annotated[str, typer.Argument(help="URL to analyze")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Write report to file")
    ] = None,
    slow_threshold: Annotated[
        int, typer.Option("--slow-threshold", help="Slow request threshold in ms")
    ] = 1000,
) -> None:
    """Analyze network requests for a URL."""
    asyncio.run(_network(url, fmt, output, slow_threshold))


async def _network(url: str, fmt: Format, output: Path | None, slow_threshold: int) -> None:
    from pagescope.models.common import SessionConfig
    from pagescope.session import DiagnosticSession

    config = SessionConfig(slow_request_threshold_ms=slow_threshold)
    console.print(f"[bold]Analyzing network for {url}...[/bold]\n")

    async with DiagnosticSession.start(config=config) as session:
        await session.network.setup()
        await session.navigate(url)
        report = await session.network.analyze()

    if fmt == Format.html:
        from pagescope.cli.html_report import render_network_html
        html_content = render_network_html(report)
        _write_output(html_content, output or Path("network-report.html"))
    else:
        format_output(report, OutputFormat(fmt.value), console)


@app.command()
def performance(
    url: Annotated[str, typer.Argument(help="URL to profile")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
    cpu_profile: Annotated[
        bool, typer.Option("--cpu-profile", help="Include CPU profiling")
    ] = False,
) -> None:
    """Profile page performance including Core Web Vitals."""
    asyncio.run(_performance(url, fmt, cpu_profile))


async def _performance(url: str, fmt: Format, cpu_profile: bool) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Profiling performance for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        session.performance._include_cpu_profile = cpu_profile
        await session.performance.setup()
        await session.navigate(url)
        report = await session.performance.analyze()

    if fmt == Format.html:
        # for HTML output, we need to convert to JSON first then render HTML
        from pagescope.cli.formatters import _render_json
        import json
        
        json_content = _render_json(report, None)
        from pagescope.cli.html_report import render_diagnostic_html
        html_content = render_diagnostic_html(report)
        _write_output(html_content, Path("performance-report.html"))
    else:
        format_output(report, OutputFormat(fmt.value), console)


@app.command(name="console")
def console_cmd(
    url: Annotated[str, typer.Argument(help="URL to monitor")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
) -> None:
    """Capture console messages and errors for a URL."""
    asyncio.run(_console(url, fmt))


async def _console(url: str, fmt: Format) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Monitoring console for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        await session.console.setup()
        await session.navigate(url)
        report = await session.console.analyze()

    format_output(report, OutputFormat(fmt.value if fmt != Format.html else "json"), console)


@app.command()
def security(
    url: Annotated[str, typer.Argument(help="URL to check")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
) -> None:
    """Check page security: TLS, mixed content, CSP."""
    asyncio.run(_security(url, fmt))


async def _security(url: str, fmt: Format) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Checking security for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        await session.security.setup()
        await session.navigate(url)
        report = await session.security.analyze()

    format_output(report, OutputFormat(fmt.value if fmt != Format.html else "json"), console)


@app.command(name="accessibility")
def accessibility_cmd(
    url: Annotated[str, typer.Argument(help="URL to audit")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
) -> None:
    """Audit page accessibility: contrast, forms, headings, ARIA."""
    asyncio.run(_accessibility(url, fmt))


async def _accessibility(url: str, fmt: Format) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Auditing accessibility for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        await session.accessibility.setup()
        await session.navigate(url)
        report = await session.accessibility.analyze()

    format_output(report, OutputFormat(fmt.value if fmt != Format.html else "json"), console)


@app.command()
def dom(
    url: Annotated[str, typer.Argument(help="URL to inspect")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
) -> None:
    """Inspect DOM structure, CSS coverage, and layout issues."""
    asyncio.run(_dom(url, fmt))


async def _dom(url: str, fmt: Format) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Inspecting DOM for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        await session.dom.setup()
        await session.navigate(url)
        report = await session.dom.analyze()

    format_output(report, OutputFormat(fmt.value if fmt != Format.html else "json"), console)


@app.command()
def interactive(
    url: Annotated[str, typer.Argument(help="URL to test interactions")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
) -> None:
    """Test interactive elements: forms, buttons, user flows."""
    asyncio.run(_interactive(url, fmt))


async def _interactive(url: str, fmt: Format) -> None:
    from pagescope.session import DiagnosticSession

    console.print(f"[bold]Testing interactive elements for {url}...[/bold]\n")

    async with DiagnosticSession.start() as session:
        await session.interactive.setup()
        await session.navigate(url)
        report = await session.interactive.analyze()

    format_output(report, OutputFormat(fmt.value if fmt != Format.html else "json"), console)


@app.command()
def crawl(
    url: Annotated[str, typer.Argument(help="Starting URL to crawl")],
    depth: Annotated[
        int, typer.Option("--depth", "-d", help="Maximum link-follow depth")
    ] = 1,
    max_pages: Annotated[
        int, typer.Option("--max-pages", "-n", help="Maximum number of pages to crawl")
    ] = 10,
    symptom: Annotated[
        Optional[list[str]],
        typer.Option("--symptom", "-s", help="Symptom to investigate (repeatable)"),
    ] = None,
    same_domain: Annotated[
        bool, typer.Option("--same-domain/--any-domain", help="Only follow same-domain links")
    ] = True,
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format")
    ] = Format.rich,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Write report to file")
    ] = None,
) -> None:
    """Crawl a site following links and run diagnostics on each page."""
    asyncio.run(_crawl(url, depth, max_pages, symptom, same_domain, fmt, output))


async def _crawl(
    url: str,
    depth: int,
    max_pages: int,
    symptoms: list[str] | None,
    same_domain: bool,
    fmt: Format,
    output: Path | None,
) -> None:
    from pagescope.crawler import Crawler
    from pagescope.orchestrator import Symptom

    parsed = [Symptom(s) for s in symptoms] if symptoms else None

    console.print(
        f"[bold]Crawling {url}[/bold] "
        f"[dim](depth={depth}, max_pages={max_pages}, "
        f"{'same domain' if same_domain else 'any domain'})[/dim]\n"
    )

    def on_page(result):
        icon = "[green]✓[/green]" if not result.error else "[red]✗[/red]"
        n = len(result.report.findings) if result.report else 0
        console.print(
            f"  {icon} [dim]depth {result.depth}[/dim] "
            f"{result.url[:80]} "
            f"[dim]({n} findings, {result.links_found} links)[/dim]"
        )

    crawler = Crawler()
    report = await crawler.crawl(
        start_url=url,
        max_depth=depth,
        symptoms=parsed,
        same_domain=same_domain,
        max_pages=max_pages,
        on_page_complete=on_page,
    )

    console.print(
        f"\n[bold]Crawl complete:[/bold] {report.pages_crawled} pages, "
        f"{len(report.aggregate_findings)} findings, "
        f"{report.crawl_duration_ms / 1000:.1f}s\n"
    )

    if fmt == Format.html:
        from pagescope.cli.html_report import render_crawl_html

        html_content = render_crawl_html(report)
        _write_output(html_content, output or Path("crawl-report.html"))
    elif fmt == Format.json:
        from pagescope.cli.formatters import _render_json

        _render_json(report, console)
    else:
        # Rich format -- show aggregate findings table
        format_output(report, OutputFormat.RICH, console)


@app.command()
def tui(
    url: Annotated[str, typer.Argument(help="URL to analyze (or use --har/--attach)")] = "",
    har: Annotated[
        Optional[Path], typer.Option("--har", help="Load a HAR file instead of a live URL")
    ] = None,
    attach: Annotated[
        Optional[str], typer.Option("--attach", help="Attach to running browser (e.g. http://localhost:9222)")
    ] = None,
) -> None:
    """Launch Textual TUI with Chrome DevTools-like network tab."""
    from pagescope.tui.app import PageScopeApp

    if attach:
        tui_app = PageScopeApp(url=url or "attaching...", attach=attach)
    elif har:
        tui_app = PageScopeApp(url=url or f"HAR: {har}", har_path=str(har))
    elif url:
        tui_app = PageScopeApp(url=url)
    else:
        console.print("[red]Provide a URL, --har file, or --attach endpoint.[/red]")
        raise typer.Exit(1)
    tui_app.run()


@app.command()
def attach(
    port: Annotated[
        int, typer.Option("--port", "-p", help="Chrome remote debugging port")
    ] = 9222,
    host: Annotated[
        str, typer.Option("--host", help="Chrome remote debugging host")
    ] = "localhost",
) -> None:
    """Attach to a running Chrome/Edge browser and monitor in the TUI.

    Start your browser with: chrome --remote-debugging-port=9222
    Then run: pagescope attach
    """
    from pagescope.tui.app import PageScopeApp

    endpoint = f"http://{host}:{port}"
    console.print(f"[bold]Attaching to browser at {endpoint}...[/bold]")
    tui_app = PageScopeApp(url="attaching...", attach=endpoint)
    tui_app.run()


@app.command(name="launch-chrome")
def launch_chrome(
    port: Annotated[
        int, typer.Option("--port", "-p", help="Remote debugging port")
    ] = 9222,
    keep_profile: Annotated[
        bool, typer.Option("--keep-profile", help="Use your default Chrome profile instead of a temp one")
    ] = False,
) -> None:
    """Launch Chrome with remote debugging enabled, then attach.

    Finds Chrome/Edge automatically, starts it with the right flags,
    and launches the TUI attached to it.
    """
    import shutil
    import subprocess
    import sys
    import tempfile
    import time

    # find Chrome or Edge
    chrome_paths = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("msedge"),
    ]

    if sys.platform == "win32":
        chrome_paths.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ])
    elif sys.platform == "darwin":
        chrome_paths.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])

    chrome_bin = None
    for p in chrome_paths:
        if p and Path(p).exists():
            chrome_bin = p
            break

    if not chrome_bin:
        console.print("[red]Could not find Chrome or Edge. Install Chrome or pass its path manually.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Found:[/bold] {chrome_bin}")

    # build launch args
    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
    ]
    if not keep_profile:
        tmp_dir = Path(tempfile.gettempdir()) / "pagescope-chrome-debug"
        tmp_dir.mkdir(exist_ok=True)
        args.append(f"--user-data-dir={tmp_dir}")
        console.print(f"[dim]Using temp profile: {tmp_dir}[/dim]")
    else:
        console.print("[dim]Using your default Chrome profile[/dim]")

    console.print(f"[bold]Launching Chrome on port {port}...[/bold]")

    # launch Chrome as a detached subprocess
    if sys.platform == "win32":
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    # wait for the debug port to be ready
    import socket

    console.print("[dim]Waiting for debug port...[/dim]")
    for _ in range(30):
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    else:
        console.print("[red]Chrome started but debug port didn't open. Is another Chrome instance running?[/red]")
        console.print("[yellow]Try: taskkill /F /IM chrome.exe  (then run this again)[/yellow]")
        raise typer.Exit(1)

    console.print(f"[green]Chrome ready on port {port}![/green] Launching TUI...\n")

    from pagescope.tui.app import PageScopeApp

    endpoint = f"http://localhost:{port}"
    tui_app = PageScopeApp(url="attaching...", attach=endpoint)
    tui_app.run()


@app.command()
def serve(
    transport: Annotated[
        str, typer.Option("--transport", "-t", help="MCP transport (stdio or sse)")
    ] = "stdio",
) -> None:
    """Start the MCP server for AI agent integration."""
    from pagescope.server.mcp import mcp

    console.print(f"[bold]Starting MCP server ({transport})...[/bold]")
    mcp.run(transport=transport)


def main() -> None:
    import os
    # suppress Node.js deprecation warnings from Playwright internals
    # (e.g. url.parse() -> WHATWG URL API)
    os.environ.setdefault("NODE_OPTIONS", "--no-deprecation")
    app()


if __name__ == "__main__":
    main()
