# pagescope

Chrome DevTools in your terminal. A real-time TUI that streams network requests, console messages, performance metrics, security analysis, and more -- powered by Playwright and CDP.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## What It Does

PageScope connects to Chrome/Edge and gives you a full DevTools experience rendered in the terminal:

- **Network tab** with live request streaming, waterfall timing visualization, headers/timing/preview detail panels
- **Console tab** with message filtering, stack traces, and a JavaScript REPL
- **Performance tab** with Core Web Vitals gauges, page flow timeline, and CPU profiler
- **Security tab** with TLS analysis, mixed content detection, CSP violations, cookie audit
- **Elements tab** with collapsible DOM source tree and browser element highlighting
- **Cookies tab** with full cookie enumeration and security flag analysis
- **WebSocket tab** with connection tracking, frame inspection, and payload viewer

6 color themes. HAR import/export. User-Agent spoofing. No-Cache mode. Works as CLI, TUI, MCP server, or Python library.

## Quick Start

### Install

```bash
# Create a virtual environment (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install pagescope
playwright install chromium
```

Or from source:

```bash
git clone https://github.com/hed0rah/pagescope.git
cd pagescope
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
playwright install chromium
```

### Easiest Way to Run

```bash
pagescope launch-chrome
```

This finds Chrome/Edge on your system, launches it with remote debugging enabled, and opens the TUI attached to it. Browse normally in Chrome -- everything streams to the TUI in real-time.

### Other Ways to Run

```bash
# Analyze a URL directly (launches headless Chromium)
pagescope tui https://example.com

# Attach to a browser you already started with --remote-debugging-port=9222
pagescope attach

# Load a HAR file for offline analysis
pagescope tui --har capture.har
```

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `q` | Quit |
| `g` | Navigate to URL |
| `f` | Filter / Search |
| `c` | Clear current tab |
| `p` | Pause / Resume |
| `t` | Cycle theme |
| `u` | Cycle User-Agent |
| `n` | Toggle No-Cache |
| `k` | Toggle Keep Log |
| `h` | Export HAR |
| `l` | Load HAR |
| `?` | Show legend |

## CLI

Run diagnostics from the command line with structured output.

```bash
# Full diagnostic
pagescope diagnose https://example.com

# Target specific symptoms
pagescope diagnose https://example.com --symptom slow_page
pagescope diagnose https://example.com --symptom api_failures --symptom console_errors

# Individual modules
pagescope network https://example.com
pagescope performance https://example.com --cpu-profile
pagescope console https://example.com
pagescope security https://example.com
pagescope accessibility https://example.com
pagescope dom https://example.com
pagescope interactive https://example.com

# Site crawl
pagescope crawl https://example.com --depth 2 --max-pages 20

# Output formats: rich (default), json, html
pagescope diagnose https://example.com --format json
pagescope diagnose https://example.com --format html --output report.html
```

## MCP Server

For use with Claude Code, Claude Desktop, or any MCP-compatible AI agent:

```bash
pagescope serve
```

Add to your MCP client config:

```json
{
  "mcpServers": {
    "pagescope": {
      "command": "pagescope",
      "args": ["serve"]
    }
  }
}
```

Exposes 14 tools: `diagnose_url`, `check_network`, `check_performance`, `check_console_errors`, `check_security`, `check_accessibility`, `check_dom`, `crawl_site`, `capture_screenshot`, `interact_with_page`, `test_user_flow`, `analyze_interactive_elements`, `test_form_submission`, `run_javascript`.

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

## Requirements

- Python 3.11+
- Playwright (`playwright install chromium`)
- Chrome or Edge (for `launch-chrome` / `attach` modes)

## Full Feature List

See [FEATURES.md](FEATURES.md) for the complete technical feature reference.

## Development

```bash
pip install -e ".[dev]"
playwright install chromium
pytest tests/
ruff check src/ tests/
```

## License

MIT
