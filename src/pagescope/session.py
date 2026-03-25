"""DiagnosticSession -- wraps Playwright browser + CDP session lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    async_playwright,
)

from pagescope.diagnostics.accessibility import AccessibilityAuditor
from pagescope.diagnostics.console import ConsoleMonitor
from pagescope.diagnostics.dom import DOMInspector
from pagescope.diagnostics.interactive import InteractiveTester
from pagescope.diagnostics.network import NetworkInspector
from pagescope.diagnostics.performance import PerformanceProfiler
from pagescope.diagnostics.security import SecurityChecker
from pagescope.models.common import SessionConfig


class DiagnosticSession:
    """Manages a Playwright browser + CDP session for diagnostic operations.

    Usage::

        async with DiagnosticSession.start(url="https://example.com") as session:
            network_report = await session.network.analyze()
            perf_report = await session.performance.analyze()
    """

    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._cdp: CDPSession | None = None
        self._attached: bool = False  # True when connected to external browser

        # lazy-initialized diagnostic modules
        self._network: NetworkInspector | None = None
        self._performance: PerformanceProfiler | None = None
        self._console: ConsoleMonitor | None = None
        self._security: SecurityChecker | None = None
        self._dom: DOMInspector | None = None
        self._accessibility: AccessibilityAuditor | None = None
        self._interactive: InteractiveTester | None = None

    @classmethod
    @asynccontextmanager
    async def start(
        cls,
        url: str | None = None,
        config: SessionConfig | None = None,
    ) -> AsyncIterator["DiagnosticSession"]:
        """Create and manage a diagnostic session lifecycle."""
        session = cls(config=config)
        try:
            await session._launch()
            if url:
                await session.navigate(url)
            yield session
        finally:
            await session._shutdown()

    @classmethod
    def from_existing(
        cls,
        page: Page,
        cdp: CDPSession,
        config: SessionConfig | None = None,
    ) -> "DiagnosticSession":
        """Create a session wrapping an existing page and CDP session.

        Used by the Crawler to share a browser instance across multiple pages.
        The caller is responsible for lifecycle management (closing context, etc.).
        """
        session = cls(config=config)
        session._page = page
        session._cdp = cdp
        return session

    async def _launch(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=self.config.browser_args or None,
        )
        self._context = await self._browser.new_context(
            viewport=self.config.viewport,
            user_agent=self.config.user_agent,
        )
        self._page = await self._context.new_page()
        self._cdp = await self._context.new_cdp_session(self._page)

    async def _connect(self, endpoint: str) -> None:
        """Connect to an existing browser via CDP (remote debugging).

        Args:
            endpoint: CDP WebSocket endpoint or http://host:port URL.
                      e.g. "http://localhost:9222"
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)

        # get the first (default) context -- the user's real browsing context
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = await self._browser.new_context()

        # get the active page (most recently used) or first available
        pages = self._context.pages
        if pages:
            self._page = pages[-1]  # Last = most recently active
        else:
            self._page = await self._context.new_page()

        self._cdp = await self._context.new_cdp_session(self._page)
        self._attached = True

    async def switch_to_page(self, page: Page) -> None:
        """Switch CDP session to a different page/tab."""
        if self._cdp:
            try:
                await self._cdp.detach()
            except Exception:
                pass
        self._page = page
        assert self._context is not None
        self._cdp = await self._context.new_cdp_session(page)
        # reset diagnostic modules so they re-bind to the new page/cdp
        self._network = None
        self._performance = None
        self._console = None
        self._security = None
        self._dom = None
        self._accessibility = None
        self._interactive = None

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for the configured lifecycle event."""
        assert self._page is not None, "Session not started"
        await self._page.goto(
            url,
            wait_until=self.config.navigation_wait_until,  # type: ignore[arg-type]
            timeout=self.config.timeout_ms,
        )

    async def _shutdown(self) -> None:
        if self._cdp:
            try:
                await self._cdp.detach()
            except Exception:
                pass
        if self._attached:
            # when attached to external browser, don't close context or browser
            # -- that's the user's real browser session
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            return
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    # --- Diagnostic module accessors (lazy init) ---

    @property
    def network(self) -> NetworkInspector:
        if self._network is None:
            self._network = NetworkInspector(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._network

    @property
    def performance(self) -> PerformanceProfiler:
        if self._performance is None:
            self._performance = PerformanceProfiler(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._performance

    @property
    def console(self) -> ConsoleMonitor:
        if self._console is None:
            self._console = ConsoleMonitor(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._console

    @property
    def security(self) -> SecurityChecker:
        if self._security is None:
            self._security = SecurityChecker(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._security

    @property
    def dom(self) -> DOMInspector:
        if self._dom is None:
            self._dom = DOMInspector(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._dom

    @property
    def accessibility(self) -> AccessibilityAuditor:
        if self._accessibility is None:
            self._accessibility = AccessibilityAuditor(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._accessibility

    @property
    def interactive(self) -> InteractiveTester:
        if self._interactive is None:
            self._interactive = InteractiveTester(
                page=self.page, cdp=self.cdp, config=self.config
            )
        return self._interactive

    @property
    def page(self) -> Page:
        assert self._page is not None, "Session not started"
        return self._page

    @property
    def cdp(self) -> CDPSession:
        assert self._cdp is not None, "Session not started"
        return self._cdp

    async def screenshot(self, full_page: bool = True) -> bytes:
        """Capture a screenshot of the current page."""
        return await self.page.screenshot(full_page=full_page)

    async def evaluate(self, expression: str) -> object:
        """Run arbitrary JavaScript in the page context."""
        return await self.page.evaluate(expression)
