# PageScope -- Web Diagnostics Skill

Use the PageScope MCP server to diagnose web pages. Match user symptoms to the right tool, interpret findings, and drill down as needed.

## Quick Dispatch

| User says... | Action |
|---|---|
| "Site is slow" / "page takes forever" | `diagnose_url(url, symptoms=["slow_page"])` |
| "Page looks broken" / "layout wrong" | `diagnose_url(url, symptoms=["page_looks_broken"])` |
| "API calls failing" / "data not loading" | `diagnose_url(url, symptoms=["api_failures"])` |
| "Security warnings" / "mixed content" | `diagnose_url(url, symptoms=["security_warnings"])` |
| "Accessibility issues" / "screen reader" | `diagnose_url(url, symptoms=["accessibility_issues"])` |
| "Just check it" / unclear | `diagnose_url(url)` -- runs general_health |

## Available Tools

| Tool | Purpose | When to Use |
|---|---|---|
| `diagnose_url` | Full diagnostic with symptom routing | Default -- handles most scenarios |
| `check_network` | HTTP request/response analysis | API failures, slow loading, missing resources |
| `check_performance` | Core Web Vitals + metrics | Slow pages, jank, layout shifts |
| `check_console_errors` | Console messages + exceptions | First step for any misbehavior |
| `check_security` | TLS, mixed content, CSP, cookies | Security audits |
| `check_accessibility` | Contrast, ARIA, forms, headings | Accessibility audits |
| `check_dom` | DOM structure, CSS coverage | Layout issues, bloated pages |
| `capture_screenshot` | Visual page capture | See what the page looks like |
| `run_javascript` | Custom JS evaluation | Inspect specific DOM state |
| `crawl_site` | Multi-page crawl with diagnostics | Site-wide audits |

## Key Principles

1. **Console first** -- `check_console_errors` is the fastest signal. Start here if unsure.
2. **Symptom-driven** -- Don't run everything. Match symptoms to the right tool.
3. **Read severity** -- Focus on CRITICAL/ERROR findings first, then warnings.
4. **Drill down** -- Use specific tools to investigate findings from `diagnose_url`.

## Decision Trees

### Site Is Slow

1. `check_console_errors(url)` -- JS exceptions can halt execution
2. `check_network(url)` -- check `slow_requests` and timing breakdowns:
   - High `dns_ms` → slow DNS, use preconnect
   - High `wait_ms` (TTFB) → server-side problem, not frontend
   - High `receive_ms` → large payloads, compress or paginate
   - `total_transfer_bytes > 5MB` → page too heavy, check `requests_by_type`
3. `check_performance(url)` -- check Web Vitals:
   - LCP > 2500ms → optimize largest visible element (hero image, text block)
   - FCP > 1800ms → render-blocking CSS/JS, inline critical CSS
   - TTFB > 800ms → backend/server issue
   - CLS > 0.1 → add dimensions to images/embeds

### API Calls Failing

1. `check_console_errors(url)` -- look for fetch/XHR errors
2. `check_network(url)` -- filter for failed requests:
   - 4xx → client-side issue (wrong URL, auth, CORS)
   - 5xx → server-side error
   - 0/cancelled → CORS blocked, network error, or aborted
3. `check_security(url)` -- mixed content can silently block API calls

### Page Looks Broken

1. `capture_screenshot(url)` -- see what's actually rendering
2. `check_console_errors(url)` -- JS errors often cause blank/broken pages
3. `check_dom(url)` -- check for layout issues, missing elements
4. `check_network(url)` -- missing CSS/JS resources break rendering

### Security Warnings

1. `check_security(url)` -- TLS status, mixed content, CSP violations, cookie flags
2. `check_network(url)` -- identify insecure requests (http:// on https:// page)

### Accessibility Issues

1. `check_accessibility(url)` -- contrast ratios, form labels, heading hierarchy, ARIA
2. `check_dom(url)` -- DOM structure, landmark regions

## Output Format

All tools return structured JSON. Key fields in `diagnose_url` response:

```json
{
  "url": "...",
  "findings": [
    {
      "severity": "error",
      "category": "console",
      "title": "...",
      "description": "...",
      "recommendation": "..."
    }
  ],
  "flows": [
    {
      "module": "network",
      "status": "completed",
      "report": {},
      "duration_ms": 1234
    }
  ],
  "recommendations": []
}
```
