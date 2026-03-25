# PageScope -- Feature Reference

Technical feature list for PageScope v0.2.0.

---

## TUI (Terminal User Interface)

Built on [Textual](https://textual.textualize.io/).

### 7 Tabs

#### Network Tab
- **Live request table** -- Streams HTTP requests as they happen via CDP `Network` domain events (`requestWillBeSent`, `responseReceived`, `loadingFinished`, `loadingFailed`)
- **Columns**: Status code, method, filename, type, size (transfer), time (ms), and waterfall
- **Waterfall visualization** -- ASCII timing bar per request showing:
  - DNS lookup (blue)
  - TCP connect (green)
  - SSL/TLS handshake (purple)
  - Server wait / TTFB (yellow)
  - Content download (cyan)
  - Queued time (dim)
  - Colors are theme-aware and survive DataTable cursor highlighting using `░` shading
- **Detail panel** -- Select a request to see:
  - Headers tab (request + response headers)
  - Timing tab (full timing breakdown in ms)
  - Preview tab (response body preview with JSON pretty-printing)
- **Filtering** -- Filter by resource type: All, Doc, JS, CSS, Img, XHR, Font, Media, Other
- **Search** -- Full-text search across request URLs
- **Summary bar** -- Live counts: total requests, transferred size, load time, DOMContentLoaded
- **No-Cache mode** (`n`) -- Sets `Cache-Control: no-cache` on all requests via CDP `Network.setCacheDisabled`
- **Keep Log** (`k`) -- Preserves requests across navigations instead of clearing

#### Console Tab
- **Live console message stream** -- Captures `console.log`, `.warn`, `.error`, `.info`, `.debug` via CDP `Runtime.consoleAPICalled`
- **Unhandled exceptions** -- Catches `Runtime.exceptionThrown` events
- **Severity filtering** -- All, Errors, Warnings, Info, Debug, Violations
- **Search** -- Full-text search across console messages
- **Detail view** -- Select a message to see full stack trace, source location, and arguments
- **JavaScript REPL** -- Evaluate expressions live via CDP `Runtime.evaluate` with results displayed inline
- **Pause/Resume** (`p`) -- Freeze the stream to inspect messages without scrolling

#### Performance Tab
- **Three sub-views** toggled with `v`:
  1. **Metrics** -- Core Web Vitals gauge display:
     - LCP (Largest Contentful Paint)
     - FCP (First Contentful Paint)
     - CLS (Cumulative Layout Shift)
     - TTFB (Time to First Byte)
     - Color-coded thresholds (green/yellow/red per Google's Web Vitals guidelines)
     - Additional metrics: DOM nodes, JS heap size, layout count, style recalcs
  2. **Page Flow** -- Visual timeline showing:
     - Page load milestones (TTFB, FCP, DCL, LCP, Load) as colored time markers
     - Resource waterfall: up to 60 requests with method, status, ASCII timing bar, duration, and URL path
     - Color-coded by resource type (document, script, stylesheet, image, xhr, fetch, etc.)
  3. **Profiler** -- CPU profile capture and display (via CDP `Profiler` domain)
- **Refresh metrics** (`r`) -- Re-collects Web Vitals from the current page

#### Security Tab
- **TLS certificate details** -- Protocol version, cipher suite, issuer, validity dates via CDP `Security.securityStateChanged`
- **Mixed content detection** -- Flags HTTP resources loaded on HTTPS pages
- **CSP violations** -- Content Security Policy violation tracking
- **Insecure form detection** -- Forms that POST over HTTP
- **Cookie security audit** -- Flags cookies missing `Secure`, `HttpOnly`, or `SameSite` attributes
- **Security score** -- Overall security health rating

#### Elements Tab
- **DOM metrics summary** -- Total nodes, depth, text nodes, forms, images, links, scripts, iframes
- **Collapsible source tree** -- Full DOM tree rendered in a Textual `Tree` widget via CDP `DOM.getDocument(depth=-1, pierce=true)`
  - Syntax-colored node labels: tags (bold cyan), attributes (yellow), values (green), text content (dim), comments (dim green)
  - Caps at 2,000 nodes / depth 50 to prevent memory issues
- **Browser highlighting** -- Hovering over a node in the tree triggers CDP `Overlay.highlightNode` to highlight the element in the browser with a DevTools-style blue content / green padding / orange margin overlay
- **DOM re-scan** (`r`) -- Re-fetches the DOM tree to reflect runtime changes

#### Cookies Tab
- **Cookie table** -- All cookies for the current page with columns: Name, Value, Domain, Path, Secure, HttpOnly, SameSite, Expires
- **Detail view** -- Full cookie attributes on selection
- **Security flags** -- Visual indicators for missing security attributes

#### WebSocket Tab
- **Connection list** -- All WebSocket connections with status (open/closed), URL, frame counts, transfer size, duration
- **Frame inspector** -- Select a connection to see individual frames in a sortable table
- **Direction filtering** -- All, Sent, Received
- **Payload viewer** -- Select a frame to see full payload with JSON pretty-printing
- **Frame search** -- Full-text search across frame payloads
- **Pause/Resume** (`p`) -- Freeze frame capture

### TUI Global Features

- **URL navigation** (`g`) -- Enter a new URL to navigate to without restarting
- **Theme cycling** (`t`) -- 6 built-in themes: Devtools (default), Monokai, Solarized, Dracula, Nord, Killengn
- **User-Agent spoofing** (`u`) -- Cycle through user agent presets (desktop, mobile, tablet, bot) with live emulation via CDP
- **HAR export** (`h`) -- Export all captured network traffic as HAR 1.2 files
- **HAR import** (`l`) -- Load and replay HAR files in the network tab for offline analysis
- **Legend overlay** (`?`) -- Toggle a color/symbol reference panel explaining waterfall colors, status codes, and resource types
- **Pause** (`p`) -- Freeze all live data streams
- **Clear** (`c`) -- Clear current tab data
- **Filter** (`f`) -- Focus the filter/search input

### Launch Modes

1. **`pagescope tui <url>`** -- Launches a headless Chromium via Playwright, navigates to the URL, streams all data to the TUI
2. **`pagescope tui --attach http://localhost:9222`** -- Attaches to an already-running Chrome/Edge with remote debugging enabled (you browse normally, TUI shows everything)
3. **`pagescope launch-chrome`** -- Finds Chrome/Edge on your system, launches it with `--remote-debugging-port=9222`, waits for the debug port, then opens the TUI attached to it. The easiest way to get started.
4. **`pagescope tui --har capture.har`** -- Loads a HAR file for offline analysis without any browser

---

## CLI Commands

Individual diagnostic commands for scripted or one-shot use.

| Command | Description |
|---|---|
| `pagescope diagnose <url>` | Full diagnostic with optional `--symptom` targeting |
| `pagescope network <url>` | Network request analysis with timing breakdown |
| `pagescope performance <url>` | Core Web Vitals + optional `--cpu-profile` |
| `pagescope console <url>` | Console messages and unhandled exceptions |
| `pagescope security <url>` | TLS, mixed content, CSP, cookie security |
| `pagescope accessibility <url>` | Contrast, form labels, headings, alt text, ARIA |
| `pagescope dom <url>` | DOM size, CSS coverage, layout issues |
| `pagescope interactive <url>` | Form, button, and interactive element testing |
| `pagescope crawl <url>` | BFS site crawl with per-page diagnostics |
| `pagescope tui <url>` | Launch the interactive TUI |
| `pagescope attach` | Attach TUI to running browser |
| `pagescope launch-chrome` | Auto-find Chrome, launch with debug port, attach TUI |
| `pagescope serve` | Start MCP server for AI agent integration |

### Symptom-Based Targeting

Pass `--symptom` to `diagnose` or `crawl` to run only the relevant modules:

| Symptom | Modules |
|---|---|
| `slow_page` | performance, network, dom |
| `broken_layout` | console, network, dom |
| `api_failures` | network, console, security |
| `console_errors` | console, network |
| `security_warnings` | security, network, console |
| `accessibility_issues` | accessibility, dom, console |
| `interactive_issues` | interactive, console, dom, network |
| `general_health` | console, network, performance, security, accessibility |

### Output Formats

- **Rich** (default) -- Color-formatted terminal output via Rich
- **JSON** -- Machine-readable structured output, pipe to `jq` or ingest programmatically
- **HTML** -- Self-contained HTML reports with interactive charts, expandable sections, severity filtering, and responsive design. No external dependencies.

---

## MCP Server (AI Agent Integration)

Start with `pagescope serve`. Exposes 14 tools via [FastMCP](https://github.com/jlowin/fastmcp) over stdio or SSE transport.

| Tool | Description |
|---|---|
| `diagnose_url` | Full diagnostic with symptom list and optional screenshot |
| `check_network` | HTTP request analysis with configurable slow threshold |
| `check_performance` | Core Web Vitals with optional CPU profile |
| `check_console_errors` | Console messages and unhandled exceptions |
| `check_security` | TLS, mixed content, CSP analysis |
| `check_accessibility` | Accessibility audit |
| `check_dom` | DOM structure and CSS coverage |
| `crawl_site` | Multi-page crawl with per-page diagnostics |
| `capture_screenshot` | Full-page PNG as base64 |
| `interact_with_page` | Execute click/type/select actions on page elements |
| `test_user_flow` | Run multi-step user flow definitions |
| `analyze_interactive_elements` | Discover and assess interactive elements |
| `test_form_submission` | Fill and submit forms with validation |
| `run_javascript` | Evaluate arbitrary JS in page context |

Compatible with Claude Code, Claude Desktop, and any MCP-compatible client.

---

## Diagnostic Modules (Technical)

### Network (`diagnostics/network.py`)
- CDP domains: `Network`, `Page`
- Captures: `requestWillBeSent`, `responseReceived`, `loadingFinished`, `loadingFailed`
- Timing via `Network.getResponseBody` and `ResourceTiming` API
- Detects: failed requests (4xx/5xx), slow requests (configurable threshold), large transfers, redirect chains

### Performance (`diagnostics/performance.py`)
- CDP domains: `Performance`, `Profiler`, `Page`
- Web Vitals via `PerformanceObserver` injection (LCP, FCP, CLS, TTFB)
- Additional: DOM node count, JS heap size, layout duration, style recalculation count
- Optional CPU profiling via `Profiler.start` / `Profiler.stop`

### Console (`diagnostics/console.py`)
- CDP domains: `Runtime`, `Log`
- Captures: `consoleAPICalled`, `exceptionThrown`
- Classifies by severity: error, warning, info, debug, verbose
- Tracks violations (long tasks, forced reflows)

### Security (`diagnostics/security.py`)
- CDP domains: `Security`, `Network`
- TLS analysis: protocol version, cipher suite, certificate chain
- Mixed content: HTTP resources on HTTPS pages
- CSP violation tracking via `SecurityPolicyViolation` events
- Cookie audit: `Secure`, `HttpOnly`, `SameSite` attribute validation
- Form action analysis for insecure POST targets

### Accessibility (`diagnostics/accessibility.py`)
- Playwright accessibility tree + DOM queries
- Contrast ratio calculation (WCAG AA/AAA thresholds)
- Form label association (`<label for="">`, `aria-label`, `aria-labelledby`)
- Heading hierarchy validation (skipped levels, multiple `<h1>`)
- Image `alt` attribute checking
- ARIA role and attribute validation

### DOM (`diagnostics/dom.py`)
- CDP domain: `DOM`, `CSS`
- DOM complexity metrics: total nodes, max depth, element distribution
- CSS coverage via `CSS.startRuleUsageTracking`
- Layout issue detection: viewport meta, overflow, inline styles
- Script and stylesheet enumeration

### Interactive (`diagnostics/interactive.py`)
- CDP domains: `DOM`, `Runtime`, `Input`
- Discovers forms, buttons, links, inputs
- Tests visibility, enabled state, click handlers
- Form validation: required fields, input types, action URLs

### Cookies (`diagnostics/cookies.py`)
- CDP domain: `Network.getCookies`
- Enumerates all cookies with security attribute analysis
- Flags: missing `Secure` on HTTPS, missing `HttpOnly`, `SameSite=None` without `Secure`

### Forensics (`diagnostics/forensics.py`)
- Deep-dive analysis module for CTF/forensics use cases
- Technology fingerprinting, hidden element discovery, metadata extraction

---

## Data & Export

- **HAR 1.2 Export/Import** (`export/har.py`) -- Full HTTP Archive format support. Export captures from TUI, import for offline replay.
- **Pydantic Models** -- All diagnostic results are structured Pydantic v2 models (`models/` directory) for type-safe serialization to JSON/dict.
- **HTML Reports** -- Self-contained single-file reports with embedded CSS/JS, interactive charts (via inline SVG), severity-based color coding, expandable details.

---

## Themes

Six built-in color themes affecting the entire TUI:

| Theme | Style |
|---|---|
| **Devtools** | Dark blue slate -- inspired by Chrome DevTools |
| **Monokai** | Warm dark -- the classic editor palette |
| **Solarized** | Ethan Schoonover's balanced dark palette |
| **Dracula** | Purple-accented dark theme |
| **Nord** | Arctic, blue-tinted color scheme |
| **Killengn** | High-contrast teal-magenta cyberpunk |

Each theme defines: background, card background, alt background, border, text, dim text, accent, status colors (green/yellow/red/cyan/blue), and 6 waterfall phase colors.

---

## Python API

```python
from pagescope.session import DiagnosticSession
from pagescope.orchestrator import Orchestrator, Symptom

async with DiagnosticSession.start() as session:
    orchestrator = Orchestrator(session)
    report = await orchestrator.diagnose(
        url="https://example.com",
        symptoms=[Symptom.SLOW_PAGE],
    )
    for finding in report.findings:
        print(f"{finding.severity}: {finding.title}")
```

All session modules (`session.network`, `session.performance`, etc.) are also usable individually for targeted analysis.

---

## Requirements

- Python 3.11+
- Playwright (with Chromium)
- Chrome or Edge (for `launch-chrome` and `attach` modes)
- Terminal with Unicode support (for waterfall rendering)
