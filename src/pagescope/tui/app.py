"""Main Textual App -- Chrome DevTools in the terminal."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static, TabbedContent, TabPane

from pagescope.data import load_user_agents
from pagescope.tui.console import ConsoleTab
from pagescope.tui.cookies import CookiesTab
from pagescope.tui.elements import ElementsTab
from pagescope.tui.network import NetworkTab
from pagescope.tui.performance import PerformanceTab
from pagescope.tui.security import SecurityTab
from pagescope.tui.themes import THEME_NAMES, THEMES, get_theme_css
from pagescope.tui.websocket import WebSocketTab


def _normalize_url(url: str) -> str:
    """Add https:// if no scheme is provided."""
    if url and not url.startswith(("http://", "https://", "file://", "data:")):
        return f"https://{url}"
    return url


class PageScopeApp(App):
    """PageScope TUI -- Chrome DevTools in the terminal."""

    TITLE = "pagescope"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("c", "clear", "Clear", show=True),
        Binding("p", "pause", description="Pause", show=False),
        Binding("f", "filter", "Filter", show=True),
        Binding("t", "cycle_theme", "Theme", show=True),
        Binding("g", "goto_url", "Address Bar", show=True),
        Binding("u", "cycle_ua", "User-Agent", show=True),
        Binding("n", "toggle_nocache", description="No-Cache", show=False),
        Binding("h", "export_har", "HAR Export", show=True),
        Binding("l", "load_har", "Load HAR", show=True),
        Binding("k", "toggle_preserve_log", description="Keep Log", show=False),
        Binding("F5", "refresh_page", "Refresh", show=False, priority=True),
        Binding("alt+left", "go_back", "Back", show=False, priority=True),
        Binding("1", "switch_tab_1", show=False),
        Binding("2", "switch_tab_2", show=False),
        Binding("3", "switch_tab_3", show=False),
        Binding("4", "switch_tab_4", show=False),
        Binding("5", "switch_tab_5", show=False),
        Binding("6", "switch_tab_6", show=False),
        Binding("7", "switch_tab_7", show=False),
        Binding("question_mark", "show_legend", "Legend", show=True),
    ]

    def __init__(
        self, url: str, har_path: str | None = None,
        attach: str | None = None, **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._url = _normalize_url(url)
        self._har_path = har_path
        self._attach_endpoint = attach  # e.g. "http://localhost:9222"
        self._session = None
        self._capture_task: asyncio.Task | None = None
        self._console_task: asyncio.Task | None = None
        self._security_task: asyncio.Task | None = None
        self._performance_task: asyncio.Task | None = None
        self._theme_index: int = 0
        self._navigating: bool = False
        self._ua_list: list[dict] = load_user_agents()
        self._ua_index: int = 0
        self._nocache: bool = False
        self._preserve_log: bool = False
        self._inspector = None
        self._legend_visible: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="header-bar"):
            yield Button("\u25c0", id="nav-back", classes="nav-btn")
            yield Button("\u25b6", id="nav-forward", classes="nav-btn")
            yield Button("\u21bb", id="nav-refresh", classes="nav-btn")
            yield Input(value=self._url, id="url-input", placeholder="enter URL...")
            yield Input(placeholder="Path to .har file...", id="har-input", classes="hidden")
            yield Label("connecting...", id="status-label")
            yield Label("\\[n] No-Cache", id="toggle-nocache", classes="toggle-off")
            yield Label("\\[k] Keep Log", id="toggle-keeplog", classes="toggle-off")
            yield Label("\\[p] Pause ", id="toggle-paused", classes="toggle-off")
        with TabbedContent():
            with TabPane("Network", id="tab-network"):
                yield NetworkTab()
            with TabPane("Console", id="tab-console"):
                yield ConsoleTab()
            with TabPane("Performance", id="tab-performance"):
                yield PerformanceTab()
            with TabPane("Security", id="tab-security"):
                yield SecurityTab()
            with TabPane("Elements", id="tab-elements"):
                yield ElementsTab()
            with TabPane("Cookies", id="tab-cookies"):
                yield CookiesTab()
            with TabPane("WebSocket", id="tab-websocket"):
                yield WebSocketTab()
        yield Static("", id="legend-overlay", classes="hidden")
        yield Footer()

    async def on_mount(self) -> None:
        # Set initial theme colors on the network tab for waterfall rendering
        try:
            initial_theme = THEMES[THEME_NAMES[self._theme_index]]
            self.query_one(NetworkTab)._theme_colors = initial_theme
        except Exception:
            pass

        if self._har_path:
            await self._do_load_har(self._har_path)
        elif self._attach_endpoint:
            self._capture_task = asyncio.create_task(self._run_attach())
        else:
            self._capture_task = asyncio.create_task(self._run_capture())

    async def _run_capture(self) -> None:
        """Start browser session and stream network + console events to the TUI."""
        from pagescope.diagnostics.network import NetworkInspector
        from pagescope.models.common import SessionConfig
        from pagescope.session import DiagnosticSession

        network_tab = self.query_one(NetworkTab)
        console_tab = self.query_one(ConsoleTab)
        security_tab = self.query_one(SecurityTab)
        perf_tab = self.query_one(PerformanceTab)
        elements_tab = self.query_one(ElementsTab)
        cookies_tab = self.query_one(CookiesTab)
        ws_tab = self.query_one(WebSocketTab)
        status = self.query_one("#status-label", Label)

        try:
            config = SessionConfig()
            session = DiagnosticSession(config=config)
            self._session = session

            # launch browser
            status.update("launching browser...")
            await session._launch()

            # create network inspector with real-time callbacks
            def on_request_complete(request):
                network_tab.add_request(request)
                perf_tab.add_request(request)

            def on_ws_frame(conn, frame):
                ws_tab.add_frame(conn, frame)

            inspector = NetworkInspector(
                page=session.page,
                cdp=session.cdp,
                config=config,
                on_request_complete=on_request_complete,
                on_ws_frame=on_ws_frame,
            )

            # setup network + console + security + performance + DOM monitoring
            status.update("setting up capture...")
            await inspector.setup()
            await session.console.setup()
            await session.security.setup()
            await session.performance.setup()
            await session.dom.setup()

            # wire element search callback
            elements_tab._search_callback = lambda sel: asyncio.create_task(
                self._search_elements(session, elements_tab, sel)
            )

            # wire DOM highlight callback (visible in attach mode with a real browser)
            elements_tab._highlight_callback = lambda node_id: asyncio.create_task(
                self._highlight_node(session, node_id)
            )

            # wire body search callback
            network_tab._body_search_callback = lambda pattern: asyncio.create_task(
                self._search_response_bodies(inspector, network_tab, pattern)
            )

            # wire replay callback
            network_tab._replay_callback = lambda method, url, headers, body: asyncio.create_task(
                self._replay_request(session, network_tab, method, url, headers, body)
            )

            # wire CPU profile callback
            perf_tab._profile_callback = lambda duration: asyncio.create_task(
                self._run_cpu_profile(session, perf_tab, duration)
            )

            # wire console eval callback
            console_tab._eval_callback = lambda expr: asyncio.create_task(
                self._eval_js(session, console_tab, expr)
            )

            # start console stream in background
            self._console_task = asyncio.create_task(
                self._stream_console(session, console_tab)
            )

            # start security event stream in background
            self._security_task = asyncio.create_task(
                self._stream_security(session, security_tab)
            )

            # navigate
            status.update(f"loading {self._url}...")
            await session.navigate(self._url)

            status.update(f"capturing -- {self._url}")

            # wait for page load
            try:
                await session.page.wait_for_load_state("networkidle", timeout=30000)
                status.update(f"idle -- {self._url}")
            except Exception:
                status.update(f"loaded -- {self._url}")

            # store inspector reference for response body search
            self._inspector = inspector

            # run full security + performance + DOM + forensics + cookies analysis
            await self._run_security_scan(session, security_tab)
            await self._run_performance_scan(session, perf_tab)
            await self._run_elements_scan(session, elements_tab)
            await self._fetch_dom_tree(session, elements_tab)
            await self._run_forensics(session, inspector, security_tab, elements_tab)
            await self._run_cookie_scan(inspector, cookies_tab)

            # feed existing requests to performance flow view
            perf_tab.load_requests(list(inspector._requests.values()))

            # keep session alive; check for rescan requests
            while True:
                await asyncio.sleep(1)
                if security_tab._scan_pending:
                    security_tab._scan_pending = False
                    await self._run_security_scan(session, security_tab)
                if perf_tab._scan_pending:
                    perf_tab._scan_pending = False
                    await self._run_performance_scan(session, perf_tab)
                if elements_tab._scan_pending:
                    elements_tab._scan_pending = False
                    await self._run_elements_scan(session, elements_tab)
                    await self._fetch_dom_tree(session, elements_tab)
                if cookies_tab._scan_pending:
                    cookies_tab._scan_pending = False
                    await self._run_cookie_scan(inspector, cookies_tab)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            status.update(f"error: {exc}")

    async def _run_attach(self) -> None:
        """Attach to an existing browser via CDP and stream events."""
        from pagescope.diagnostics.network import NetworkInspector
        from pagescope.models.common import SessionConfig
        from pagescope.session import DiagnosticSession

        network_tab = self.query_one(NetworkTab)
        console_tab = self.query_one(ConsoleTab)
        security_tab = self.query_one(SecurityTab)
        perf_tab = self.query_one(PerformanceTab)
        elements_tab = self.query_one(ElementsTab)
        cookies_tab = self.query_one(CookiesTab)
        ws_tab = self.query_one(WebSocketTab)
        status = self.query_one("#status-label", Label)

        try:
            config = SessionConfig()
            session = DiagnosticSession(config=config)
            self._session = session

            status.update(f"connecting to {self._attach_endpoint}...")
            await session._connect(self._attach_endpoint)

            # show the active page's URL
            current_url = session.page.url
            self._url = current_url
            try:
                self.query_one("#url-input", Input).value = current_url
            except Exception:
                pass

            # Set up network inspector with real-time callbacks
            def on_request_complete(request):
                network_tab.add_request(request)
                perf_tab.add_request(request)

            def on_ws_frame(conn, frame):
                ws_tab.add_frame(conn, frame)

            inspector = NetworkInspector(
                page=session.page,
                cdp=session.cdp,
                config=config,
                on_request_complete=on_request_complete,
                on_ws_frame=on_ws_frame,
            )

            status.update("setting up capture...")
            await inspector.setup()
            await session.console.setup()
            await session.security.setup()
            await session.performance.setup()
            await session.dom.setup()

            # wire callbacks
            elements_tab._search_callback = lambda sel: asyncio.create_task(
                self._search_elements(session, elements_tab, sel)
            )
            elements_tab._highlight_callback = lambda node_id: asyncio.create_task(
                self._highlight_node(session, node_id)
            )
            network_tab._body_search_callback = lambda pattern: asyncio.create_task(
                self._search_response_bodies(inspector, network_tab, pattern)
            )
            network_tab._replay_callback = lambda method, url, headers, body: asyncio.create_task(
                self._replay_request(session, network_tab, method, url, headers, body)
            )
            perf_tab._profile_callback = lambda duration: asyncio.create_task(
                self._run_cpu_profile(session, perf_tab, duration)
            )

            # wire console eval callback
            console_tab._eval_callback = lambda expr: asyncio.create_task(
                self._eval_js(session, console_tab, expr)
            )

            # console stream
            self._console_task = asyncio.create_task(
                self._stream_console(session, console_tab)
            )
            self._security_task = asyncio.create_task(
                self._stream_security(session, security_tab)
            )

            self._inspector = inspector
            status.update(f"attached -- {current_url}")

            # run initial scans
            await self._run_security_scan(session, security_tab)
            await self._run_performance_scan(session, perf_tab)
            await self._run_elements_scan(session, elements_tab)
            await self._fetch_dom_tree(session, elements_tab)
            await self._run_forensics(session, inspector, security_tab, elements_tab)
            await self._run_cookie_scan(inspector, cookies_tab)

            # feed existing requests to performance flow view
            perf_tab.load_requests(list(inspector._requests.values()))

            # ── Set up page event listener for new tabs ──
            _new_pages: list = []

            def _on_new_page(page):
                _new_pages.append(page)

            if session._context:
                session._context.on("page", _on_new_page)

            # ── Clear on navigation (fires before new requests stream in) ──
            def _on_frame_navigated(frame):
                # only main frame, not iframes
                if frame != session.page.main_frame:
                    return
                if not self._preserve_log:
                    self.action_clear()

            session.page.on("framenavigated", _on_frame_navigated)

            # monitor for page navigations and tab switches
            last_url = current_url

            while True:
                await asyncio.sleep(1)

                # handle new tab opened
                if _new_pages:
                    new_page = _new_pages.pop()
                    _new_pages.clear()
                    try:
                        # wait briefly for the new page to have a URL
                        await asyncio.sleep(0.5)
                        await self._switch_attached_tab(
                            session, new_page, config,
                            on_request_complete, on_ws_frame,
                            perf_tab, security_tab, elements_tab, cookies_tab,
                        )
                        inspector = self._inspector
                        last_url = self._url
                        status.update(f"new tab -- {self._url}")
                    except Exception as exc:
                        status.update(f"tab error: {exc}")
                    continue

                # detect URL change (user navigated within the same tab)
                try:
                    new_url = session.page.url
                except Exception:
                    continue

                if new_url != last_url:
                    last_url = new_url
                    self._url = new_url
                    try:
                        self.query_one("#url-input", Input).value = new_url
                        status.update(f"navigated -- {new_url}")
                    except Exception:
                        pass

                    # clearing is handled by framenavigated event
                    # (fires synchronously before new requests stream in)

                    # re-run scans on the new page
                    try:
                        await self._run_security_scan(session, security_tab)
                        await self._run_elements_scan(session, elements_tab)
                        await self._fetch_dom_tree(session, elements_tab)
                        await self._run_forensics(session, inspector, security_tab, elements_tab)
                        await self._run_cookie_scan(inspector, cookies_tab)
                    except Exception:
                        pass

                # handle rescan requests from tabs
                if security_tab._scan_pending:
                    security_tab._scan_pending = False
                    await self._run_security_scan(session, security_tab)
                if perf_tab._scan_pending:
                    perf_tab._scan_pending = False
                    await self._run_performance_scan(session, perf_tab)
                if elements_tab._scan_pending:
                    elements_tab._scan_pending = False
                    await self._run_elements_scan(session, elements_tab)
                    await self._fetch_dom_tree(session, elements_tab)
                if cookies_tab._scan_pending:
                    cookies_tab._scan_pending = False
                    await self._run_cookie_scan(inspector, cookies_tab)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            status.update(f"attach error: {exc}")

    async def _switch_attached_tab(
        self, session, page, config,
        on_request_complete, on_ws_frame,
        perf_tab, security_tab, elements_tab, cookies_tab,
    ) -> None:
        """Switch the attached session to a different browser tab."""
        from pagescope.diagnostics.network import NetworkInspector

        await session.switch_to_page(page)

        # re-create inspector for the new page
        inspector = NetworkInspector(
            page=session.page,
            cdp=session.cdp,
            config=config,
            on_request_complete=on_request_complete,
            on_ws_frame=on_ws_frame,
        )
        await inspector.setup()
        await session.performance.setup()
        self._inspector = inspector

        new_url = session.page.url
        self._url = new_url

        if not self._preserve_log:
            self.action_clear()

        try:
            self.query_one("#url-input", Input).value = new_url
        except Exception:
            pass

        # re-run scans
        try:
            await self._run_security_scan(session, security_tab)
            await self._run_performance_scan(session, perf_tab)
            await self._run_elements_scan(session, elements_tab)
            await self._run_forensics(session, inspector, security_tab, elements_tab)
            await self._run_cookie_scan(inspector, cookies_tab)
        except Exception:
            pass

    async def _stream_console(self, session, console_tab: ConsoleTab) -> None:
        """Stream console events from the ConsoleMonitor to the Console Tab."""
        try:
            async for event in session.console.stream():
                if event.type == "message" and event.entry:
                    console_tab.add_entry(event.entry)
                elif event.type == "exception" and event.exception:
                    console_tab.add_exception(event.exception)
                elif event.type == "violation" and event.violation:
                    console_tab.add_violation(event.violation)
        except asyncio.CancelledError:
            pass

    async def _stream_security(self, session, security_tab: SecurityTab) -> None:
        """Stream real-time security events to the Security Tab."""
        try:
            async for event in session.security.stream():
                security_tab.add_event(event.type, event.detail)
        except asyncio.CancelledError:
            pass

    async def _run_security_scan(self, session, security_tab: SecurityTab) -> None:
        """Run full security analysis and load results into the tab."""
        try:
            report = await session.security.analyze()
            security_tab.load_report(report)
        except Exception:
            pass

    async def _run_performance_scan(self, session, perf_tab: PerformanceTab) -> None:
        """Run full performance analysis and load results into the tab."""
        try:
            report = await session.performance.analyze()
            perf_tab.load_report(report)
            # feed FCP to network tab for waterfall ruler
            if report.web_vitals and report.web_vitals.fcp_ms:
                try:
                    net_tab = self.query_one(NetworkTab)
                    net_tab._fcp_ms = report.web_vitals.fcp_ms
                    net_tab._update_waterfall_header()
                except Exception:
                    pass
        except Exception:
            pass

    async def _run_cpu_profile(self, session, perf_tab: PerformanceTab, duration: int) -> None:
        """Run a CPU profile and load results into the performance tab."""
        try:
            profile = await session.performance.profile_cpu(duration_seconds=float(duration))
            # update the report with the new profile
            if perf_tab._report:
                perf_tab._report.cpu_profile = profile
                perf_tab.load_cpu_profile(perf_tab._report)
            else:
                from pagescope.models.performance import PerformanceReport
                report = PerformanceReport(cpu_profile=profile)
                perf_tab.load_cpu_profile(report)
            perf_tab.on_profile_complete()
        except Exception as exc:
            perf_tab.on_profile_complete()
            try:
                self.query_one("#cpu-status-label", Label).update(f"Error: {exc}")
            except Exception:
                pass

    async def _eval_js(self, session, console_tab: ConsoleTab, expression: str) -> None:
        """Evaluate a JavaScript expression via CDP Runtime.evaluate and display the result."""
        try:
            cdp = session.cdp
            # use Runtime.evaluate for richer result info than page.evaluate
            result = await cdp.send("Runtime.evaluate", {
                "expression": expression,
                "generatePreview": True,
                "returnByValue": False,
                "awaitPromise": True,
                "userGesture": True,
            })

            exc_details = result.get("exceptionDetails")
            remote_obj = result.get("result", {})

            if exc_details:
                # evaluation threw an error
                err_text = exc_details.get("text", "")
                err_exception = exc_details.get("exception", {})
                description = err_exception.get("description", err_text)
                stack = ""
                if err_exception.get("preview"):
                    props = err_exception["preview"].get("properties", [])
                    for p in props:
                        if p.get("name") == "stack":
                            stack = p.get("value", "")
                            break
                console_tab.add_eval_result(expression, {
                    "type": "error",
                    "value": description,
                    "description": description,
                    "stack": stack,
                    "error": True,
                })
            else:
                # successful result
                obj_type = remote_obj.get("type", "undefined")
                subtype = remote_obj.get("subtype", "")
                class_name = remote_obj.get("className", "")
                description = remote_obj.get("description", "")
                value = remote_obj.get("value")

                # for objects, try to get a useful preview
                preview = remote_obj.get("preview")
                if preview and obj_type == "object":
                    display = self._format_object_preview(preview)
                elif obj_type == "undefined":
                    display = "undefined"
                elif obj_type == "function":
                    display = description or "function"
                elif value is not None:
                    display = value
                else:
                    display = description or str(value)

                console_tab.add_eval_result(expression, {
                    "type": obj_type,
                    "subtype": subtype,
                    "className": class_name,
                    "value": display,
                    "description": str(display),
                    "error": False,
                })

                # release the remote object to avoid leaks
                obj_id = remote_obj.get("objectId")
                if obj_id:
                    try:
                        await cdp.send("Runtime.releaseObject", {"objectId": obj_id})
                    except Exception:
                        pass

        except Exception as exc:
            console_tab.add_eval_result(expression, {
                "type": "error",
                "value": str(exc),
                "description": str(exc),
                "error": True,
            })

    def _format_object_preview(self, preview: dict) -> str:
        """Format a CDP Runtime.ObjectPreview into a readable string."""
        obj_type = preview.get("type", "object")
        subtype = preview.get("subtype", "")
        description = preview.get("description", "")
        props = preview.get("properties", [])
        overflow = preview.get("overflow", False)

        if subtype == "array":
            items = []
            for p in props:
                val = p.get("value", "")
                if p.get("type") == "string":
                    items.append(f'"{val}"')
                else:
                    items.append(str(val))
            suffix = ", ..." if overflow else ""
            return f"[{', '.join(items)}{suffix}]"
        elif subtype == "null":
            return "null"
        elif subtype in ("regexp", "date"):
            return description
        else:
            # generic object
            pairs = []
            for p in props:
                name = p.get("name", "")
                val = p.get("value", "")
                if p.get("type") == "string":
                    pairs.append(f'{name}: "{val}"')
                elif p.get("type") == "object":
                    pairs.append(f"{name}: {p.get('value', '...')}")
                else:
                    pairs.append(f"{name}: {val}")
            suffix = ", ..." if overflow else ""
            prefix = f"{description} " if description and description != "Object" else ""
            return f"{prefix}{{{', '.join(pairs)}{suffix}}}"

    async def _run_elements_scan(self, session, elements_tab: ElementsTab) -> None:
        """Run full DOM analysis and load results into the tab."""
        try:
            report = await session.dom.analyze()
            elements_tab.load_report(report)
        except Exception:
            pass

    async def _fetch_dom_tree(self, session, elements_tab: ElementsTab) -> None:
        """Fetch the full DOM tree via CDP and load into Elements tab."""
        try:
            cdp = session.cdp
            result = await cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})
            elements_tab.load_dom_tree(result.get("root", {}))
        except Exception:
            pass

    async def _highlight_node(self, session, backend_node_id: int) -> None:
        """Highlight a DOM node in the browser using CDP Overlay."""
        try:
            cdp = session.cdp
            await cdp.send("Overlay.enable", {})
            await cdp.send("Overlay.highlightNode", {
                "highlightConfig": {
                    "showInfo": True,
                    "showStyles": False,
                    "showRulers": False,
                    "showAccessibilityInfo": True,
                    "contentColor": {"r": 111, "g": 168, "b": 220, "a": 0.66},
                    "paddingColor": {"r": 147, "g": 196, "b": 125, "a": 0.55},
                    "borderColor": {"r": 255, "g": 229, "b": 153, "a": 0.75},
                    "marginColor": {"r": 246, "g": 178, "b": 107, "a": 0.66},
                },
                "backendNodeId": backend_node_id,
            })
        except Exception:
            pass

    async def _run_forensics(self, session, inspector, security_tab: SecurityTab, elements_tab: ElementsTab) -> None:
        """Run forensics analysis and distribute results to tabs."""
        try:
            from pagescope.diagnostics.forensics import run_forensics

            # get main document response headers from the inspector
            response_headers = {}
            for req in inspector._requests.values():
                if req.resource_type == "Document" and req.response_headers:
                    response_headers = req.response_headers
                    break

            report = await run_forensics(session.page, response_headers)

            # load security headers into Security tab
            security_tab.load_headers_report(report.security_headers)

            # load forensics into Elements tab
            elements_tab.load_forensics(report)
        except Exception:
            pass

    async def _run_cookie_scan(self, inspector, cookies_tab: CookiesTab) -> None:
        """Fetch and analyze all cookies."""
        try:
            from pagescope.diagnostics.cookies import get_cookie_jar

            report = await get_cookie_jar(inspector._cdp, self._url)
            cookies_tab.load_report(report)
        except Exception:
            pass

    async def _search_response_bodies(self, inspector, network_tab: NetworkTab, pattern: str) -> None:
        """Search all captured response bodies for a pattern."""
        try:
            from pagescope.diagnostics.forensics import search_response_bodies

            matches = search_response_bodies(
                list(inspector._requests.values()), pattern
            )
            network_tab.load_body_search_results(matches)
        except Exception:
            network_tab.load_body_search_results([])

    async def _replay_request(
        self, session, network_tab: NetworkTab,
        method: str, url: str, headers: dict, body: str,
    ) -> None:
        """Replay a request using fetch() inside the browser page."""
        try:
            from pagescope.tui.replay import ReplayPanel

            # build fetch options as a JS expression
            result = await session.page.evaluate("""
                async ({ method, url, headers, body }) => {
                    try {
                        const opts = { method, headers, credentials: 'include' };
                        if (body && method !== 'GET' && method !== 'HEAD') {
                            opts.body = body;
                        }
                        const resp = await fetch(url, opts);
                        const respHeaders = {};
                        resp.headers.forEach((v, k) => { respHeaders[k] = v; });
                        let respBody = '';
                        try {
                            respBody = await resp.text();
                        } catch(e) {}
                        return {
                            status: resp.status,
                            statusText: resp.statusText,
                            headers: respHeaders,
                            body: respBody.substring(0, 10000),
                            ok: resp.ok,
                        };
                    } catch(e) {
                        return {
                            status: 0,
                            statusText: e.message || 'Network Error',
                            headers: {},
                            body: e.stack || e.message || String(e),
                            ok: false,
                        };
                    }
                }
            """, {"method": method, "url": url, "headers": headers, "body": body})

            # send result to the replay panel
            try:
                replay = network_tab.query_one(ReplayPanel)
                replay.set_response(result)
            except Exception:
                pass

        except Exception as exc:
            try:
                from pagescope.tui.replay import ReplayPanel
                replay = network_tab.query_one(ReplayPanel)
                replay.set_response({
                    "status": 0,
                    "statusText": f"Error: {exc}",
                    "headers": {},
                    "body": str(exc),
                    "ok": False,
                })
            except Exception:
                pass

    async def _search_elements(self, session, elements_tab: ElementsTab, selector: str) -> None:
        """Search for elements matching a CSS selector."""
        try:
            results = await session.page.evaluate("""
                (selector) => {
                    try {
                        const els = document.querySelectorAll(selector);
                        const results = [];
                        for (const el of [...els].slice(0, 100)) {
                            const rect = el.getBoundingClientRect();
                            const attrs = {};
                            for (const attr of el.attributes) {
                                attrs[attr.name] = attr.value;
                            }
                            const classStr = el.className;
                            results.push({
                                tag: el.tagName.toLowerCase(),
                                id: el.id || '',
                                classes: typeof classStr === 'string' ? classStr : '',
                                text: (el.textContent || '').trim().substring(0, 200),
                                attributes: attrs,
                                attrs_display: [...el.attributes].map(a => `${a.name}="${a.value}"`).join(' ').substring(0, 100),
                                bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                            });
                        }
                        return results;
                    } catch(e) {
                        return [];
                    }
                }
            """, selector)
            elements_tab.load_search_results(results or [])
        except Exception:
            elements_tab.load_search_results([])

    async def on_unmount(self) -> None:
        """Cleanup browser session on exit."""
        for task in (self._console_task, self._security_task, self._performance_task, self._capture_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._session:
            await self._session._shutdown()

    def _update_toggle_styles(self, t: dict[str, str] | None = None) -> None:
        """Update toggle indicator inline styles based on current state."""
        if t is None:
            t = THEMES[THEME_NAMES[self._theme_index]]
        toggles = [
            ("#toggle-nocache", self._nocache),
            ("#toggle-keeplog", self._preserve_log),
            ("#toggle-paused", hasattr(self, '_session') and self._get_paused_state()),
        ]
        for selector, is_on in toggles:
            try:
                w = self.query_one(selector, Label)
                if is_on:
                    w.remove_class("toggle-off")
                    w.add_class("toggle-on")
                    w.styles.color = t["bg"]
                    w.styles.background = t["yellow"]
                    w.styles.text_style = "bold"
                else:
                    w.remove_class("toggle-on")
                    w.add_class("toggle-off")
                    w.styles.color = t["border"]
                    w.styles.background = "transparent"
                    w.styles.text_style = "none"
            except Exception:
                pass

    def _get_paused_state(self) -> bool:
        """Check if capture is currently paused."""
        try:
            return self.query_one(NetworkTab).paused
        except Exception:
            return False

    def action_clear(self) -> None:
        try:
            self.query_one(NetworkTab).action_clear_requests()
        except Exception:
            pass
        try:
            self.query_one(ConsoleTab).action_clear_console()
        except Exception:
            pass
        try:
            self.query_one(WebSocketTab).action_clear_frames()
        except Exception:
            pass

    def action_pause(self) -> None:
        try:
            self.query_one(NetworkTab).action_toggle_pause()
        except Exception:
            pass
        try:
            self.query_one(ConsoleTab).action_toggle_pause()
        except Exception:
            pass
        try:
            self.query_one(WebSocketTab).action_toggle_pause()
        except Exception:
            pass
        self._update_toggle_styles()
        # update label text to reflect state
        try:
            paused = self._get_paused_state()
            lbl = self.query_one("#toggle-paused", Label)
            lbl.update("\\[p] Paused" if paused else "\\[p] Pause ")
        except Exception:
            pass

    def action_filter(self) -> None:
        try:
            self.query_one(NetworkTab).action_focus_filter()
        except Exception:
            pass
        try:
            self.query_one(ConsoleTab).action_focus_filter()
        except Exception:
            pass

    def action_cycle_theme(self) -> None:
        """Cycle through available color themes."""
        self._theme_index = (self._theme_index + 1) % len(THEME_NAMES)
        name = THEME_NAMES[self._theme_index]
        t = THEMES[name]
        self._apply_theme(t)
        try:
            self.query_one("#status-label", Label).update(f"theme: {name}")
        except Exception:
            pass

    def action_show_legend(self) -> None:
        """Toggle the legend overlay explaining colors and symbols."""
        try:
            overlay = self.query_one("#legend-overlay", Static)
        except Exception:
            return

        if self._legend_visible:
            overlay.add_class("hidden")
            self._legend_visible = False
            return

        t = THEMES[THEME_NAMES[self._theme_index]]
        legend_text = (
            "[bold]  Legend[/bold]\n"
            "\n"
            "  [bold]Waterfall Timing Phases[/bold]\n"
            f"    [{t['wf-dns']}]██[/{t['wf-dns']}] DNS Lookup      "
            f"[{t['wf-connect']}]██[/{t['wf-connect']}] TCP Connect     "
            f"[{t['wf-ssl']}]██[/{t['wf-ssl']}] SSL/TLS\n"
            f"    [{t['wf-wait']}]██[/{t['wf-wait']}] Waiting (TTFB)  "
            f"[{t['wf-download']}]██[/{t['wf-download']}] Download        "
            f"[dim]····[/dim] Queued\n"
            "\n"
            "  [bold]Web Vitals[/bold]\n"
            "    [green]██[/green] Good    [yellow]██[/yellow] Needs Work    [red]██[/red] Poor\n"
            "\n"
            "  [bold]HTTP Status[/bold]\n"
            "    [green]2xx[/green] Success    [yellow]3xx[/yellow] Redirect    [red]4xx/5xx[/red] Error\n"
            "\n"
            "  [bold]Resource Types (Page Flow)[/bold]\n"
            "    [blue]██[/blue] Document    [yellow]██[/yellow] Script    [green]██[/green] CSS\n"
            "    [cyan]██[/cyan] Image/Media    [dim]██[/dim] Font\n"
            "\n"
            "  [bold]Elements Tree[/bold]\n"
            "    [bold cyan]tag[/bold cyan] [yellow]attr[/yellow]=[green]\"value\"[/green]"
            "    [dim]\"text\"[/dim]    [dim green]<!-- comment -->[/dim green]\n"
            "\n"
            "  [dim]Press ? to close[/dim]"
        )
        overlay.update(legend_text)
        overlay.remove_class("hidden")
        self._legend_visible = True

    def _apply_theme(self, t: dict[str, str]) -> None:
        """Apply a theme by directly updating widget styles."""
        from textual.color import Color

        # update waterfall colors on the network tab and rebuild bars
        try:
            network_tab = self.query_one(NetworkTab)
            network_tab._theme_colors = t
            network_tab._rebuild_table()
        except Exception:
            pass

        screen = self.screen
        screen.styles.background = t["bg"]
        accent = t["accent"]
        border_color = Color.parse(t["border"])

        # header bar
        for w in self.query("#header-bar"):
            w.styles.background = t["bg-card"]
            w.styles.border_bottom = ("solid", border_color)
        for w in self.query("#header-bar Label"):
            w.styles.color = t["text"]
        for w in self.query("#url-input"):
            w.styles.color = accent
            w.styles.background = t["bg-card"]
            w.styles.border = ("none", "transparent")
        for w in self.query("#status-label"):
            w.styles.color = t["text-dim"]
        # toggle indicators
        self._update_toggle_styles(t)

        # all card-bg bars (filter bars, overview panels, vitals bar, search bars)
        card_bars = [
            "#filter-bar", "#console-filter-bar", "#security-filter-bar",
            "#perf-vitals-bar", "#security-overview", "#elements-overview",
            "#elements-search-bar", "#cookies-filter-bar", "#cookies-overview",
            "#body-search-bar", "#ws-filter-bar", "#ws-overview",
            "#replay-header", "#perf-cpu-controls", "#console-input-bar",
        ]
        for bar_id in card_bars:
            for w in self.query(bar_id):
                w.styles.background = t["bg-card"]
                w.styles.border_bottom = ("solid", border_color)

        # all view-tab bars (dark bg)
        tab_bars = [
            "#detail-tabs", "#security-view-tabs", "#perf-view-tabs",
            "#elements-view-tabs", "#replay-tabs",
        ]
        for bar_id in tab_bars:
            for w in self.query(bar_id):
                w.styles.background = t["bg"]
                w.styles.border_bottom = ("solid", border_color)

        # all buttons in any bar -- unified underline style
        all_bars = card_bars + tab_bars
        for bar_id in all_bars:
            for w in self.query(f"{bar_id} Button"):
                w.styles.color = t["text-dim"]
                w.styles.background = "transparent"
            for w in self.query(f"{bar_id} Button.active"):
                w.styles.color = accent

        # console eval prompt
        for w in self.query("#console-prompt"):
            w.styles.color = t["cyan"]
        for w in self.query("#console-input-bar"):
            w.styles.background = t["bg-alt"]
        for w in self.query("#console-eval-input"):
            w.styles.background = t["bg"]
            w.styles.color = t["text"]

        # vitals bar labels
        for w in self.query("#perf-vitals-bar Label"):
            w.styles.color = t["text"]

        # tables
        for w in self.query("DataTable"):
            w.styles.background = t["bg"]

        # DOM source tree
        for w in self.query("#dom-tree"):
            w.styles.background = t["bg"]

        # legend overlay
        for w in self.query("#legend-overlay"):
            w.styles.background = t["bg-card"]
            w.styles.border = ("solid", border_color)
            w.styles.color = t["text"]

        # headers view
        for w in self.query("#security-headers-view"):
            w.styles.background = t["bg"]
        for w in self.query("#headers-scorecard-content"):
            w.styles.color = t["text"]

        # detail / content panels
        detail_panels = [
            "#detail-panel", "#console-detail", "#security-detail",
            "#elements-search-detail", "#cookies-detail", "#ws-detail",
        ]
        for panel_id in detail_panels:
            for w in self.query(panel_id):
                w.styles.background = t["bg-card"]
                w.styles.border_top = ("solid", border_color)

        # content views (transparent bg)
        content_views = [
            "#perf-vitals-view", "#perf-cpu-view", "#perf-flow-view", "#perf-recs-view",
            "#elements-dom-view", "#elements-comments-view",
        ]
        for vid in content_views:
            for w in self.query(vid):
                w.styles.background = t["bg"]

        # static content text
        for w in self.query("Static"):
            try:
                w.styles.color = t["text"]
            except Exception:
                pass

        # summary bars
        summary_bars = [
            "#summary-bar", "#console-summary", "#security-summary",
            "#perf-summary", "#elements-summary", "#cookies-summary",
            "#ws-summary", "#replay-status",
        ]
        for bar_id in summary_bars:
            for w in self.query(bar_id):
                w.styles.background = t["bg-card"]
                w.styles.border_top = ("solid", border_color)
            for w in self.query(f"{bar_id} Label"):
                w.styles.color = t["text-dim"]

        # footer
        for w in self.query("Footer"):
            w.styles.background = t["bg-card"]

        self.refresh(layout=True)

    async def action_refresh_page(self) -> None:
        """Reload the current page."""
        if not self._session or not self._session.page or self._navigating:
            return
        await self._navigate_to(self._url)

    async def action_go_back(self) -> None:
        """Navigate back in browser history."""
        if not self._session or not self._session.page or self._navigating:
            return
        try:
            if not self._preserve_log:
                self.action_clear()
            await self._session.page.go_back(timeout=10000)
            new_url = self._session.page.url
            self._url = new_url
            self.query_one("#url-input", Input).value = new_url
        except Exception:
            pass

    async def action_go_forward(self) -> None:
        """Navigate forward in browser history."""
        if not self._session or not self._session.page or self._navigating:
            return
        try:
            if not self._preserve_log:
                self.action_clear()
            await self._session.page.go_forward(timeout=10000)
            new_url = self._session.page.url
            self._url = new_url
            self.query_one("#url-input", Input).value = new_url
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "nav-back":
            self.run_worker(self.action_go_back())
        elif btn_id == "nav-forward":
            self.run_worker(self.action_go_forward())
        elif btn_id == "nav-refresh":
            self.run_worker(self.action_refresh_page())

    _TAB_IDS = ["tab-network", "tab-console", "tab-performance", "tab-security", "tab-elements", "tab-cookies", "tab-websocket"]

    def _switch_tab(self, index: int) -> None:
        try:
            tc = self.query_one(TabbedContent)
            tc.active = self._TAB_IDS[index]
        except Exception:
            pass

    def action_switch_tab_1(self) -> None: self._switch_tab(0)
    def action_switch_tab_2(self) -> None: self._switch_tab(1)
    def action_switch_tab_3(self) -> None: self._switch_tab(2)
    def action_switch_tab_4(self) -> None: self._switch_tab(3)
    def action_switch_tab_5(self) -> None: self._switch_tab(4)
    def action_switch_tab_6(self) -> None: self._switch_tab(5)
    def action_switch_tab_7(self) -> None: self._switch_tab(6)

    def action_goto_url(self) -> None:
        """Focus the address bar for navigation."""
        try:
            url_input = self.query_one("#url-input", Input)
            url_input.focus()
            # select all text so typing replaces it
            url_input.action_select_all()
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle URL or HAR path submission from the header bar."""
        if event.input.id == "url-input":
            new_url = event.value.strip()
            if not new_url:
                return
            new_url = _normalize_url(new_url)
            event.input.value = new_url
            # unfocus the address bar back to the main content
            self.screen.focus_next()
            if new_url != self._url:
                await self._navigate_to(new_url)

        elif event.input.id == "har-input":
            har_path = event.value.strip()
            try:
                self.query_one("#har-input", Input).add_class("hidden")
            except Exception:
                pass
            self.screen.focus_next()
            if har_path:
                await self._do_load_har(har_path)

    async def action_cycle_ua(self) -> None:
        """Cycle through user agent strings."""
        self._ua_index = (self._ua_index + 1) % len(self._ua_list)
        entry = self._ua_list[self._ua_index]
        label = entry["label"]
        ua = entry["ua"] or None  # empty string = default

        try:
            status = self.query_one("#status-label", Label)
            if self._session and self._session._context:
                # apply UA via CDP Network.setUserAgentOverride
                cdp = self._session.cdp
                if ua:
                    await cdp.send(
                        "Network.setUserAgentOverride",
                        {"userAgent": ua},
                    )
                else:
                    # reset to default by sending empty override
                    await cdp.send(
                        "Network.setUserAgentOverride",
                        {"userAgent": ""},
                    )
                status.update(f"UA: {label}")
            else:
                status.update(f"UA: {label} (apply on next load)")
        except Exception as exc:
            try:
                self.query_one("#status-label", Label).update(f"UA error: {exc}")
            except Exception:
                pass

    def action_toggle_preserve_log(self) -> None:
        """Toggle preserve log -- when ON, navigation doesn't auto-clear."""
        self._preserve_log = not self._preserve_log
        self._update_toggle_styles()

    async def action_toggle_nocache(self) -> None:
        """Toggle no-cache mode -- disables browser cache via CDP."""
        self._nocache = not self._nocache
        try:
            if self._session:
                cdp = self._session.cdp
                await cdp.send(
                    "Network.setCacheDisabled",
                    {"cacheDisabled": self._nocache},
                )
        except Exception:
            pass
        self._update_toggle_styles()

    async def action_export_har(self) -> None:
        """Export captured network data as a HAR file."""
        try:
            from pagescope.export.har import export_har

            if not self._inspector or not self._inspector._requests:
                self.query_one("#status-label", Label).update("no requests to export")
                return

            # build filename from URL domain
            from urllib.parse import urlparse

            domain = urlparse(self._url).netloc.replace(":", "_") or "capture"
            ts = __import__("time").strftime("%H%M%S")
            filename = f"{domain}_{ts}.har"

            path = export_har(
                list(self._inspector._requests.values()),
                filename,
                page_url=self._url,
            )
            self.query_one("#status-label", Label).update(f"HAR saved: {path}")
        except Exception as exc:
            try:
                self.query_one("#status-label", Label).update(f"HAR error: {exc}")
            except Exception:
                pass

    def action_load_har(self) -> None:
        """Show the HAR file path input bar."""
        try:
            har_input = self.query_one("#har-input", Input)
            url_input = self.query_one("#url-input", Input)
            # toggle HAR input
            if har_input.has_class("hidden"):
                url_input.add_class("hidden")
                har_input.remove_class("hidden")
                har_input.value = ""
                har_input.focus()
            else:
                har_input.add_class("hidden")
                url_input.remove_class("hidden")
        except Exception:
            pass

    async def _do_load_har(self, path: str) -> None:
        """Load a HAR file and populate the network tab with its entries."""
        status = self.query_one("#status-label", Label)
        try:
            from pagescope.export.har import get_har_info, load_har

            # quick info check
            info = get_har_info(path)
            status.update(f"loading {info['entries']} entries from HAR...")

            # load entries as NetworkRequest objects
            requests = load_har(path)

            # push them into the network tab
            network_tab = self.query_one(NetworkTab)
            network_tab.action_clear_requests()

            for req in requests:
                network_tab.add_request(req)

            page_title = info["page_titles"][0] if info["page_titles"] else ""
            creator = info["creator"]
            status.update(
                f"HAR loaded: {len(requests)} requests"
                + (f" -- {page_title}" if page_title else "")
                + (f" (from {creator})" if creator else "")
            )

            # update address bar to show HAR source
            try:
                self.query_one("#url-input", Input).value = f"HAR: {path}"
            except Exception:
                pass

        except FileNotFoundError:
            status.update(f"HAR file not found: {path}")
        except Exception as exc:
            status.update(f"HAR load error: {exc}")

    async def _navigate_to(self, url: str) -> None:
        """Navigate the browser to a new URL and reset capture state."""
        if self._navigating or not self._session:
            return
        self._navigating = True
        self._url = url

        status = self.query_one("#status-label", Label)
        self.query_one("#url-input", Input).value = url

        # clear existing data unless preserve log is on
        if not self._preserve_log:
            self.action_clear()

        try:
            status.update(f"loading {url}...")
            await self._session.navigate(url)
            status.update(f"capturing -- {url}")

            try:
                await self._session.page.wait_for_load_state("networkidle", timeout=30000)
                status.update(f"idle -- {url}")
            except Exception:
                status.update(f"loaded -- {url}")

            # re-run all scans on new page
            try:
                security_tab = self.query_one(SecurityTab)
                perf_tab = self.query_one(PerformanceTab)
                elements_tab = self.query_one(ElementsTab)
                cookies_tab = self.query_one(CookiesTab)

                await self._run_security_scan(self._session, security_tab)
                await self._run_performance_scan(self._session, perf_tab)
                await self._run_elements_scan(self._session, elements_tab)
                if self._inspector:
                    await self._run_forensics(self._session, self._inspector, security_tab, elements_tab)
                    await self._run_cookie_scan(self._inspector, cookies_tab)
            except Exception:
                pass
        except Exception as exc:
            status.update(f"error: {exc}")
        finally:
            self._navigating = False
