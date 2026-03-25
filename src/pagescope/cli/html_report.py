"""Self-contained HTML report generator for diagnostic and crawl reports."""

from __future__ import annotations

import html
from datetime import datetime

from pagescope.models.common import Finding, Severity
from pagescope.models.crawler import CrawlReport, PageResult
from pagescope.models.report import DiagnosticReport


# ── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """\
:root {
    --critical: #dc2626;
    --error: #ef4444;
    --warning: #f59e0b;
    --info: #3b82f6;
    --success: #10b981;
    --bg: #0f172a;
    --bg-card: #1e293b;
    --bg-table-alt: #283548;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --border: #334155;
    --accent: #6366f1;
    --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}
*, *::before, *::after { box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
    color: var(--text);
    margin: 0;
    padding: 0;
    line-height: 1.6;
}
.container { max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }

/* Header */
header {
    background: linear-gradient(135deg, var(--bg-card), #1a1a2e);
    border-bottom: 3px solid var(--accent);
    padding: 2rem 0;
    margin-bottom: 2rem;
}
header .container { padding-top: 0; padding-bottom: 0; }
header h1 {
    margin: 0 0 0.5rem 0;
    font-size: 1.75rem;
    font-weight: 700;
    color: white;
}
.meta { color: var(--text-dim); font-size: 0.9rem; }
.meta a { color: var(--accent); text-decoration: none; }
.meta a:hover { text-decoration: underline; }
.meta span { margin-right: 1.5rem; }

/* Summary stats */
.stats {
    display: flex;
    gap: 1rem;
    margin: 1.5rem 0;
    flex-wrap: wrap;
}
.stat {
    padding: 1rem 1.5rem;
    border-radius: 8px;
    background: var(--bg-card);
    border-left: 4px solid var(--border);
    min-width: 140px;
    text-align: center;
}
.stat .number { font-size: 2rem; font-weight: 700; display: block; }
.stat .label { font-size: 0.8rem; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.05em; }
.stat.critical { border-left-color: var(--critical); }
.stat.critical .number { color: var(--critical); }
.stat.error { border-left-color: var(--error); }
.stat.error .number { color: var(--error); }
.stat.warning { border-left-color: var(--warning); }
.stat.warning .number { color: var(--warning); }
.stat.info { border-left-color: var(--info); }
.stat.info .number { color: var(--info); }
.stat.success { border-left-color: var(--success); }
.stat.success .number { color: var(--success); }

/* Sections */
section { margin-bottom: 2rem; }
h2 {
    font-size: 1.3rem;
    font-weight: 600;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}

/* Findings table */
table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-card);
    border-radius: 8px;
    overflow: hidden;
    font-size: 0.9rem;
}
th {
    background: #0f172a;
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    color: var(--text-dim);
}
td { padding: 0.75rem 1rem; border-top: 1px solid var(--border); }
tr:nth-child(even) td { background: var(--bg-table-alt); }

/* Severity badges */
.badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.badge.critical { background: rgba(220,38,38,0.2); color: var(--critical); }
.badge.error { background: rgba(239,68,68,0.2); color: var(--error); }
.badge.warning { background: rgba(245,158,11,0.2); color: var(--warning); }
.badge.info { background: rgba(59,130,246,0.2); color: var(--info); }

/* Recommendations */
.recs { list-style: none; padding: 0; }
.recs li {
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
    background: var(--bg-card);
    border-radius: 6px;
    border-left: 3px solid var(--accent);
}
.recs li::before { content: none; }

/* Expandable details */
details {
    background: var(--bg-card);
    border-radius: 8px;
    margin-bottom: 0.75rem;
    border: 1px solid var(--border);
}
details[open] { border-color: var(--accent); }
summary {
    padding: 1rem 1.25rem;
    cursor: pointer;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
summary:hover { background: var(--bg-table-alt); border-radius: 8px; }
summary::marker { color: var(--accent); }
.detail-body { padding: 0 1.25rem 1rem 1.25rem; }

/* Modules bar */
.modules-bar {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
}
.module-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.7rem;
    background: var(--bg-card);
    border-radius: 4px;
    font-size: 0.8rem;
    border: 1px solid var(--border);
}
.module-tag .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.dot.ok { background: var(--success); }
.dot.err { background: var(--error); }

/* Footer */
footer {
    text-align: center;
    padding: 2rem 0;
    color: var(--text-dim);
    font-size: 0.8rem;
    border-top: 1px solid var(--border);
    margin-top: 2rem;
}
footer a { color: var(--accent); text-decoration: none; }

/* Crawl-specific */
.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
}
.depth-badge {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: rgba(99,102,241,0.2);
    color: var(--accent);
    border-radius: 3px;
}
.finding-count {
    font-size: 0.85rem;
    color: var(--text-dim);
    font-weight: normal;
}

/* Screenshot */
.screenshot { max-width: 100%; border-radius: 8px; border: 1px solid var(--border); margin: 1rem 0; }

/* Responsive */
@media (max-width: 640px) {
    .stats { flex-direction: column; }
    .stat { min-width: auto; }
    table { font-size: 0.8rem; }
    td, th { padding: 0.5rem; }
}
"""


# ── Helper functions ─────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


def _severity_badge(severity: str) -> str:
    return f'<span class="badge {severity}">{severity.upper()}</span>'


def _count_by_severity(findings: list[Finding] | list[dict]) -> dict[str, int]:
    counts = {"critical": 0, "error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.severity if isinstance(f, Finding) else f.get("severity", "info")
        sev_val = sev.value if hasattr(sev, "value") else str(sev)
        if sev_val in counts:
            counts[sev_val] += 1
    return counts


def _stats_html(findings: list[Finding] | list[dict], extra_stats: list[tuple[str, str, str]] | None = None) -> str:
    """Render summary stat boxes."""
    counts = _count_by_severity(findings)
    parts = []
    for sev_name, css_class in [("critical", "critical"), ("error", "error"), ("warning", "warning"), ("info", "info")]:
        parts.append(
            f'<div class="stat {css_class}">'
            f'<span class="number">{counts[sev_name]}</span>'
            f'<span class="label">{sev_name}</span>'
            f'</div>'
        )
    if extra_stats:
        for value, label, css_class in extra_stats:
            parts.append(
                f'<div class="stat {css_class}">'
                f'<span class="number">{_esc(value)}</span>'
                f'<span class="label">{_esc(label)}</span>'
                f'</div>'
            )
    return f'<div class="stats">{"".join(parts)}</div>'


def _findings_table(findings: list[Finding] | list[dict]) -> str:
    """Render a findings table."""
    if not findings:
        return '<p style="color: var(--success); font-weight: 600;">No issues found.</p>'

    rows = []
    for f in findings:
        if isinstance(f, Finding):
            sev, cat, title, desc = f.severity.value, f.category, f.title, f.description
            source = f.details.get("source_url", "")
        else:
            sev = f.get("severity", "info")
            if hasattr(sev, "value"):
                sev = sev.value
            cat = f.get("category", "")
            title = f.get("title", "")
            desc = f.get("description", "")
            source = f.get("details", {}).get("source_url", "")

        source_cell = f'<td><a href="{_esc(source)}" target="_blank">{_esc(_truncate(source, 40))}</a></td>' if source else '<td></td>'
        rows.append(
            f"<tr>"
            f"<td>{_severity_badge(sev)}</td>"
            f"<td>{_esc(cat)}</td>"
            f"<td><strong>{_esc(title)}</strong></td>"
            f"<td>{_esc(desc)}</td>"
            f"{source_cell}"
            f"</tr>"
        )

    has_source = any(
        (f.details.get("source_url") if isinstance(f, Finding) else f.get("details", {}).get("source_url"))
        for f in findings
    )
    source_header = '<th>Page</th>' if has_source else '<th></th>'

    return (
        f'<table>'
        f'<thead><tr><th>Severity</th><th>Category</th><th>Title</th><th>Description</th>{source_header}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table>'
    )


def _recommendations_html(recs: list[str]) -> str:
    if not recs:
        return ""
    items = "".join(f"<li>{_esc(r)}</li>" for r in recs)
    return f'<section><h2>Recommendations</h2><ol class="recs">{items}</ol></section>'


def _performance_chart_html(vitals: dict) -> str:
    """Render a simple performance chart for Web Vitals."""
    if not vitals:
        return ""
    
    # create simple inline SVG chart
    lcp = vitals.get("lcp_ms", 0)
    fcp = vitals.get("fcp_ms", 0)
    cls = vitals.get("cls", 0)
    ttfb = vitals.get("ttfb_ms", 0)
    
    # normalize values for chart (0-4000ms for LCP/FCP/TTFB, 0-1 for CLS)
    max_time = 4000
    max_cls = 1.0
    
    lcp_pct = min(100, (lcp / max_time) * 100) if lcp else 0
    fcp_pct = min(100, (fcp / max_time) * 100) if fcp else 0
    ttfb_pct = min(100, (ttfb / max_time) * 100) if ttfb else 0
    cls_pct = min(100, (cls / max_cls) * 100) if cls else 0
    
    return f'''
<section>
<h2>Performance Metrics</h2>
<div style="background: var(--bg-card); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
    <svg width="100%" height="120" viewBox="0 0 400 120">
        <!-- Background grid -->
        <rect x="0" y="0" width="400" height="120" fill="var(--bg-card)" rx="4"/>
        <line x1="0" y1="40" x2="400" y2="40" stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2"/>
        <line x1="0" y1="80" x2="400" y2="80" stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2"/>
        
        <!-- LCP -->
        <rect x="40" y="{40 - lcp_pct * 0.4}" width="40" height="{lcp_pct * 0.4}" fill="var(--error)" opacity="0.8"/>
        <text x="60" y="115" text-anchor="middle" font-size="12" fill="var(--text-dim)">LCP</text>
        <text x="60" y="35" text-anchor="middle" font-size="10" fill="var(--text)">{lcp:.0f}ms</text>
        
        <!-- FCP -->
        <rect x="120" y="{40 - fcp_pct * 0.4}" width="40" height="{fcp_pct * 0.4}" fill="var(--warning)" opacity="0.8"/>
        <text x="140" y="115" text-anchor="middle" font-size="12" fill="var(--text-dim)">FCP</text>
        <text x="140" y="35" text-anchor="middle" font-size="10" fill="var(--text)">{fcp:.0f}ms</text>
        
        <!-- TTFB -->
        <rect x="200" y="{40 - ttfb_pct * 0.4}" width="40" height="{ttfb_pct * 0.4}" fill="var(--info)" opacity="0.8"/>
        <text x="220" y="115" text-anchor="middle" font-size="12" fill="var(--text-dim)">TTFB</text>
        <text x="220" y="35" text-anchor="middle" font-size="10" fill="var(--text)">{ttfb:.0f}ms</text>
        
        <!-- CLS -->
        <rect x="280" y="{40 - cls_pct * 40}" width="40" height="{cls_pct * 40}" fill="var(--success)" opacity="0.8"/>
        <text x="300" y="115" text-anchor="middle" font-size="12" fill="var(--text-dim)">CLS</text>
        <text x="300" y="35" text-anchor="middle" font-size="10" fill="var(--text)">{cls:.3f}</text>
        
        <!-- Labels -->
        <text x="20" y="25" font-size="12" fill="var(--text-dim)">4000ms</text>
        <text x="20" y="65" font-size="12" fill="var(--text-dim)">2000ms</text>
        <text x="20" y="105" font-size="12" fill="var(--text-dim)">0ms</text>
    </svg>
</div>
</section>
'''


def _modules_bar(flows: list[dict]) -> str:
    """Render the module status bar."""
    tags = []
    for flow in flows:
        status = flow.get("status", "unknown")
        dot_class = "ok" if status == "completed" else "err"
        dur = flow.get("duration_ms")
        dur_str = f" ({dur:.0f}ms)" if dur else ""
        tags.append(
            f'<span class="module-tag">'
            f'<span class="dot {dot_class}"></span>'
            f'{_esc(flow.get("module", "?"))}{_esc(dur_str)}'
            f'</span>'
        )
    return f'<div class="modules-bar">{"".join(tags)}</div>'


def _truncate(s: str, max_len: int = 80) -> str:
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


# ── Single-page report ───────────────────────────────────────────────────────

def render_diagnostic_html(report: DiagnosticReport) -> str:
    """Render a single-page DiagnosticReport as self-contained HTML."""
    data = report.model_dump()
    findings = report.findings
    flows = data.get("flows", [])
    timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    # extract performance data if available
    performance_chart_html = ""
    for flow in flows:
        if flow.get("module") == "performance" and flow.get("report"):
            vitals = flow["report"].get("web_vitals", {})
            if vitals:
                performance_chart_html = _performance_chart_html(vitals)
                break

    screenshot_html = ""
    if report.screenshot_base64:
        screenshot_html = (
            f'<section><h2>Screenshot</h2>'
            f'<img class="screenshot" src="data:image/png;base64,{report.screenshot_base64}" alt="Page screenshot" />'
            f'</section>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PageScope Report -- {_esc(report.url)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<div class="container">
<h1>PageScope Diagnostic Report</h1>
<div class="meta">
<span><a href="{_esc(report.url)}" target="_blank">{_esc(report.url)}</a></span>
<span>{_esc(timestamp)}</span>
</div>
{_modules_bar(flows)}
</div>
</header>

<div class="container">
<section>
<h2>Summary</h2>
{_stats_html(findings)}
</section>

{performance_chart_html}

<section>
<h2>Findings</h2>
{_findings_table(findings)}
</section>

{_recommendations_html(report.recommendations)}
{screenshot_html}
</div>

<footer>
Generated by <a href="https://github.com/pagescope/pagescope">PageScope</a>
</footer>
</body>
</html>"""


# ── Multi-page crawl report ──────────────────────────────────────────────────

def render_crawl_html(report: CrawlReport) -> str:
    """Render a multi-page CrawlReport as self-contained HTML."""
    timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    duration_str = f"{report.crawl_duration_ms / 1000:.1f}s" if report.crawl_duration_ms else "?"

    extra_stats = [
        (str(report.pages_crawled), "Pages", "success"),
        (duration_str, "Duration", "info"),
    ]

    # per-page detail sections
    page_sections = []
    for i, pr in enumerate(report.page_results, 1):
        n_findings = len(pr.report.findings)
        error_html = f'<p style="color: var(--error);">Error: {_esc(pr.error)}</p>' if pr.error else ""
        finding_label = f"{n_findings} finding{'s' if n_findings != 1 else ''}"

        flows = pr.report.model_dump().get("flows", [])

        page_sections.append(f"""
<details{"" if i > 1 else " open"}>
<summary>
<div class="page-header">
<span>Page {i}: <a href="{_esc(pr.url)}" target="_blank">{_esc(_truncate(pr.url, 70))}</a></span>
<span class="depth-badge">depth {pr.depth}</span>
<span class="finding-count">{finding_label} &middot; {pr.links_found} links</span>
</div>
</summary>
<div class="detail-body">
{error_html}
{_modules_bar(flows)}
{_findings_table(pr.report.findings)}
</div>
</details>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PageScope Crawl Report -- {_esc(report.start_url)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<div class="container">
<h1>PageScope Crawl Report</h1>
<div class="meta">
<span>Start: <a href="{_esc(report.start_url)}" target="_blank">{_esc(report.start_url)}</a></span>
<span>Depth: {report.max_depth}</span>
<span>{_esc(timestamp)}</span>
</div>
</div>
</header>

<div class="container">
<section>
<h2>Aggregate Summary</h2>
{_stats_html(report.aggregate_findings, extra_stats)}
</section>

<section>
<h2>All Findings ({len(report.aggregate_findings)})</h2>
{_findings_table(report.aggregate_findings)}
</section>

{_recommendations_html(report.recommendations)}

<section>
<h2>Pages ({report.pages_crawled})</h2>
{"".join(page_sections)}
</section>
</div>

<footer>
Generated by <a href="https://github.com/pagescope/pagescope">PageScope</a>
</footer>
</body>
</html>"""


def render_network_html(report: NetworkReport) -> str:
    """Render a network report as a standalone HTML page with Chrome DevTools-like interface."""
    # build request table with detailed headers
    requests_html = ""
    for req in report.requests:
        status_class = "status-success" if req.status < 400 else "status-error"
        headers_html = ""
        for key, value in req.request_headers.items():
            headers_html += f"<div><strong>{key}:</strong> {value}</div>"
        
        requests_html += f"""
        <tr>
            <td class="method">{req.method}</td>
            <td class="url">{req.url}</td>
            <td class="status {status_class}">{req.status}</td>
            <td class="type">{req.resource_type}</td>
            <td class="size">{req.decoded_body_length or 0}</td>
            <td class="time">{req.timing.total_ms if req.timing else 0:.0f}ms</td>
            <td class="headers">{headers_html}</td>
        </tr>
        """

    # if no individual requests, show message
    if not report.requests:
        requests_html = "<tr><td colspan='7' style='text-align: center; color: #9ca3af;'>No individual request details available</td></tr>"

    # build slow requests table
    slow_html = ""
    for req in report.slow_requests:
        slow_html += f"""
        <tr>
            <td>{req.get('url', 'Unknown')}</td>
            <td>{req.get('duration_ms', 0):.0f}ms</td>
            <td>{req.get('resource_type', 'Unknown')}</td>
        </tr>
        """

    # build failed requests table
    failed_html = ""
    for req in report.failed_requests:
        failed_html += f"""
        <tr>
            <td>{req.get('url', 'Unknown')}</td>
            <td>{req.get('status', 0)}</td>
            <td>{req.get('failure', 'Unknown')}</td>
        </tr>
        """

    # build timing breakdown
    timing_html = ""
    for phase, duration in report.timing_breakdown.items():
        timing_html += f"""
        <div class="timing-row">
            <span class="timing-label">{phase.replace('_', ' ').title()}</span>
            <span class="timing-value">{duration:.0f}ms</span>
        </div>
        """

    # build bottlenecks
    bottlenecks_html = ""
    for bottleneck in report.bottlenecks:
        severity_class = f"severity-{bottleneck.get('severity', 'medium')}"
        bottlenecks_html += f"""
        <div class="bottleneck-item {severity_class}">
            <div class="bottleneck-header">
                <span class="bottleneck-type">{bottleneck.get('type', 'Unknown')}</span>
                <span class="bottleneck-severity">{bottleneck.get('severity', 'medium')}</span>
            </div>
            <div class="bottleneck-description">{bottleneck.get('description', '')}</div>
        </div>
        """

    # build recommendations
    recommendations_html = ""
    for rec in report.recommendations:
        recommendations_html += f"""
        <li>{rec}</li>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Network Analysis - {report.summary.total_requests} Requests</title>
    <style>
        {_CSS}
        body {{
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: #1f2937;
            color: #e5e7eb;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 1rem;
        }}
        .header {{
            background: #111827;
            border-bottom: 1px solid #374151;
            padding: 1rem;
            margin-bottom: 1rem;
        }}
        .header h1 {{
            margin: 0;
            font-size: 1.5rem;
            color: #f9fafb;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        .stat-card {{
            background: #1f2937;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2rem;
            font-weight: bold;
            color: #f9fafb;
        }}
        .stat-label {{
            color: #9ca3af;
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .main-content {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1rem;
        }}
        .panel {{
            background: #1f2937;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 1rem;
        }}
        .panel h3 {{
            margin: 0 0 1rem 0;
            color: #f9fafb;
            font-size: 1.1rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }}
        th, td {{
            padding: 0.5rem;
            text-align: left;
            border-bottom: 1px solid #374151;
        }}
        th {{
            background: #111827;
            color: #9ca3af;
            font-weight: 600;
        }}
        .method {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
            color: #60a5fa;
        }}
        .status-success {{
            color: #34d399;
        }}
        .status-error {{
            color: #f87171;
        }}
        .headers {{
            max-width: 200px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            cursor: pointer;
        }}
        .headers:hover {{
            white-space: normal;
            background: #111827;
            padding: 0.5rem;
            border-radius: 4px;
            position: relative;
            z-index: 10;
        }}
        .timing-breakdown {{
            display: grid;
            gap: 0.5rem;
        }}
        .timing-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem;
            background: #111827;
            border-radius: 4px;
        }}
        .timing-label {{
            color: #9ca3af;
        }}
        .timing-value {{
            font-weight: bold;
            color: #f9fafb;
        }}
        .bottleneck-item {{
            margin-bottom: 1rem;
            padding: 1rem;
            border-radius: 6px;
            border-left: 4px solid;
        }}
        .severity-critical {{
            background: rgba(239, 68, 68, 0.1);
            border-color: #ef4444;
        }}
        .severity-high {{
            background: rgba(245, 158, 11, 0.1);
            border-color: #f59e0b;
        }}
        .severity-medium {{
            background: rgba(59, 130, 246, 0.1);
            border-color: #3b82f6;
        }}
        .bottleneck-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        .bottleneck-type {{
            font-weight: bold;
            color: #f9fafb;
        }}
        .bottleneck-severity {{
            background: #374151;
            color: #9ca3af;
            padding: 0.25rem 0.5rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: bold;
        }}
        .recommendations {{
            list-style: none;
            padding: 0;
        }}
        .recommendations li {{
            background: #111827;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            border-radius: 4px;
            border-left: 3px solid #3b82f6;
        }}
        .filters {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}
        .filter-btn {{
            background: #374151;
            color: #9ca3af;
            border: 1px solid #475569;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.875rem;
        }}
        .filter-btn:hover {{
            background: #475569;
            color: #f9fafb;
        }}
        .filter-btn.active {{
            background: #3b82f6;
            color: white;
            border-color: #3b82f6;
        }}
        @media (max-width: 768px) {{
            .main-content {{
                grid-template-columns: 1fr;
            }}
            .headers {{
                max-width: 100px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Network Analysis</h1>
            <div class="meta">Total Requests: {report.summary.total_requests} • Total Size: {report.summary.total_transfer_bytes / 1024:.1f} KB</div>
        </header>

        <div class="summary-grid">
            <div class="stat-card">
                <div class="stat-value">{report.summary.total_requests}</div>
                <div class="stat-label">Total Requests</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{report.summary.total_transfer_bytes / 1024:.1f} KB</div>
                <div class="stat-label">Total Transfer</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{report.summary.median_response_ms or 0:.0f}ms</div>
                <div class="stat-label">Median Response</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(report.failed_requests)}</div>
                <div class="stat-label">Failed Requests</div>
            </div>
        </div>

        <div class="main-content">
            <div class="panel">
                <h3>Request Details</h3>
                <div class="filters">
                    <button class="filter-btn active" onclick="filterRequests('all')">All</button>
                    <button class="filter-btn" onclick="filterRequests('xhr')">XHR</button>
                    <button class="filter-btn" onclick="filterRequests('img')">Images</button>
                    <button class="filter-btn" onclick="filterRequests('css')">CSS</button>
                    <button class="filter-btn" onclick="filterRequests('js')">JavaScript</button>
                    <button class="filter-btn" onclick="filterRequests('failed')">Failed</button>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Method</th>
                            <th>URL</th>
                            <th>Status</th>
                            <th>Type</th>
                            <th>Size</th>
                            <th>Time</th>
                            <th>Headers</th>
                        </tr>
                    </thead>
                    <tbody>
                        {requests_html}
                    </tbody>
                </table>
            </div>

            <div class="panel">
                <h3>Performance Analysis</h3>
                
                <div style="margin-bottom: 1rem;">
                    <h4 style="margin: 0 0 0.5rem 0; color: #9ca3af; font-size: 0.875rem;">TIMING BREAKDOWN</h4>
                    <div class="timing-breakdown">
                        {timing_html}
                    </div>
                </div>

                <div style="margin-bottom: 1rem;">
                    <h4 style="margin: 0 0 0.5rem 0; color: #9ca3af; font-size: 0.875rem;">BOTTLENECKS</h4>
                    {bottlenecks_html}
                </div>

                <div>
                    <h4 style="margin: 0 0 0.5rem 0; color: #9ca3af; font-size: 0.875rem;">RECOMMENDATIONS</h4>
                    <ul class="recommendations">
                        {recommendations_html}
                    </ul>
                </div>
            </div>
        </div>

        <div style="margin-top: 1rem;">
            <div class="panel">
                <h3>Slow Requests</h3>
                <table>
                    <thead>
                        <tr>
                            <th>URL</th>
                            <th>Duration</th>
                            <th>Type</th>
                        </tr>
                    </thead>
                    <tbody>
                        {slow_html}
                    </tbody>
                </table>
            </div>

            <div class="panel" style="margin-top: 1rem;">
                <h3>Failed Requests</h3>
                <table>
                    <thead>
                        <tr>
                            <th>URL</th>
                            <th>Status</th>
                            <th>Failure</th>
                        </tr>
                    </thead>
                    <tbody>
                        {failed_html}
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            function filterRequests(type) {{
                const rows = document.querySelectorAll('tbody tr');
                const buttons = document.querySelectorAll('.filter-btn');
                
                // Update button states
                buttons.forEach(btn => btn.classList.remove('active'));
                event.target.classList.add('active');
                
                rows.forEach(row => {{
                    if (type === 'all') {{
                        row.style.display = '';
                        return;
                    }}
                    
                    const typeCell = row.querySelector('td:nth-child(4)');
                    const statusCell = row.querySelector('td:nth-child(3)');
                    
                    if (!typeCell) return;
                    
                    const requestType = typeCell.textContent.toLowerCase();
                    const isFailed = statusCell && (statusCell.textContent < 200 || statusCell.textContent >= 400);
                    
                    if (type === 'xhr' && requestType.includes('xhr')) {{
                        row.style.display = '';
                    }} else if (type === 'img' && (requestType.includes('image') || requestType.includes('img'))) {{
                        row.style.display = '';
                    }} else if (type === 'css' && requestType.includes('stylesheet')) {{
                        row.style.display = '';
                    }} else if (type === 'js' && requestType.includes('script')) {{
                        row.style.display = '';
                    }} else if (type === 'failed' && isFailed) {{
                        row.style.display = '';
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});
            }}
        </script>
    </div>
</body>
</html>
    """
