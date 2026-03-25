# Contributing to PageScope

Guidelines for contributing to the project.

## Getting Started

### Prerequisites

- Python 3.11+
- Git

### Development Setup

1. Fork and clone:

```bash
git clone https://github.com/YOUR_USERNAME/pagescope.git
cd pagescope
```

2. Create a virtual environment:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
```

3. Install in dev mode:

```bash
pip install -e ".[dev]"
playwright install chromium
```

4. Run tests:

```bash
pytest tests/
```

## Project Structure

```
pagescope/
├── src/pagescope/
│   ├── cli/              # Typer CLI commands
│   ├── diagnostics/      # Diagnostic modules (network, security, etc.)
│   ├── models/           # Pydantic data models
│   ├── tui/              # Textual TUI (app, tabs, themes)
│   ├── server/           # MCP server
│   ├── export/           # HAR export
│   ├── orchestrator.py   # Symptom → diagnostic routing
│   └── session.py        # Browser session management
├── tests/
└── docs/
```

## Adding a Diagnostic Module

Each diagnostic follows the same pattern:

1. **Model** in `src/pagescope/models/` — Pydantic dataclasses for the report
2. **Diagnostic** in `src/pagescope/diagnostics/` — inherits `BaseDiagnostic`, implements `setup()`, `analyze()`, `teardown()`
3. **TUI tab** in `src/pagescope/tui/` — Textual widget for real-time display
4. **CLI command** in `src/pagescope/cli/app.py` — Typer command
5. **MCP tool** in `src/pagescope/server/mcp.py` — optional
6. **Wire it up** in `session.py` and `orchestrator.py`

See any existing module (e.g. `diagnostics/security.py` + `models/security.py`) for the pattern.

## Writing Tests

- Use `@pytest.mark.asyncio` — all diagnostics are async
- Mock CDP and Page via fixtures in `tests/conftest.py`
- Test both success paths and error conditions

```python
@pytest.mark.asyncio
async def test_checker_setup(mock_page, mock_cdp):
    checker = ExampleChecker(mock_page, mock_cdp, SessionConfig())
    mock_cdp.send = pytest.AsyncMock(return_value={})
    await checker.setup()
    calls = [c.args[0] for c in mock_cdp.send.call_args_list]
    assert "Example.enable" in calls
```

## Code Style

- **Ruff** for linting: `ruff check src/ tests/`
- **MyPy** for types: `mypy src/`
- Line length: 99
- Type hints on all public functions
- Config is in `pyproject.toml`

## Submitting Changes

1. Create a branch: `git checkout -b feature/your-thing`
2. Make changes, add tests
3. Run `pytest`, `ruff check`, `mypy src/`
4. Push and open a PR with a clear description

Keep PRs focused — one feature or fix per PR.

## Resources

- [Playwright Python docs](https://playwright.dev/python/)
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)
- [Textual docs](https://textual.textualize.io/)
- [Pydantic docs](https://docs.pydantic.dev/)
