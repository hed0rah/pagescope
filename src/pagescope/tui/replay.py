"""Request Replay panel -- edit and resend HTTP requests."""

from __future__ import annotations

import json
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static, TextArea


HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class ReplayPanel(Widget):
    """Editable request replay panel -- modify and resend any captured request."""

    visible: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._original_request: Any = None
        self._replay_callback: Any = None  # Set by app: async fn(method, url, headers, body) -> result
        self._response_data: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="replay-container"):
            # top bar: method selector + URL
            with Horizontal(id="replay-header"):
                yield Button("GET", id="replay-method", classes="method-btn")
                yield Input(placeholder="URL", id="replay-url")
                yield Button("Send", id="replay-send", classes="send-btn")
                yield Button("Close", id="replay-close", classes="close-btn")

            # tabs: Headers | Body | Response
            with Horizontal(id="replay-tabs"):
                yield Button("Headers", id="rtab-headers", classes="active")
                yield Button("Body", id="rtab-body")
                yield Button("Response", id="rtab-response")

            # editor area
            with Vertical(id="replay-editor"):
                yield TextArea(id="replay-textarea", language="json")

            # status bar
            with Horizontal(id="replay-status"):
                yield Label("Ready", id="replay-status-label")

    def on_mount(self) -> None:
        self.add_class("hidden")

    def load_request(self, request: Any) -> None:
        """Pre-fill the replay editor with a captured request's data."""
        self._original_request = request
        self._response_data = None
        self._active_tab = "headers"

        try:
            # Set method
            method_btn = self.query_one("#replay-method", Button)
            method_btn.label = request.method

            # Set URL
            url_input = self.query_one("#replay-url", Input)
            url_input.value = request.url

            # build headers text
            self._show_headers_tab(request)

            # update status
            status = self.query_one("#replay-status-label", Label)
            status.update(f"Loaded: {request.method} {request.url[:60]}")
        except NoMatches:
            pass

    def show(self) -> None:
        """Show the replay panel."""
        self.visible = True
        self.remove_class("hidden")

    def hide(self) -> None:
        """Hide the replay panel."""
        self.visible = False
        self.add_class("hidden")

    def _show_headers_tab(self, request: Any | None = None) -> None:
        req = request or self._original_request
        if not req:
            return
        try:
            textarea = self.query_one("#replay-textarea", TextArea)
            headers = req.request_headers or {}
            # format as editable key: value pairs
            lines = [f"{k}: {v}" for k, v in headers.items()]
            textarea.load_text("\n".join(lines))

            # activate tab button
            self._set_active_tab("rtab-headers")
            self._active_tab = "headers"
        except NoMatches:
            pass

    def _show_body_tab(self) -> None:
        req = self._original_request
        try:
            textarea = self.query_one("#replay-textarea", TextArea)
            if req and req.request_body:
                # try to pretty-print JSON
                try:
                    parsed = json.loads(req.request_body)
                    textarea.load_text(json.dumps(parsed, indent=2))
                except (json.JSONDecodeError, TypeError):
                    textarea.load_text(req.request_body)
            else:
                textarea.load_text("")

            self._set_active_tab("rtab-body")
            self._active_tab = "body"
        except NoMatches:
            pass

    def _show_response_tab(self) -> None:
        try:
            textarea = self.query_one("#replay-textarea", TextArea)
            if self._response_data:
                lines = []
                lines.append(f"Status: {self._response_data.get('status', '?')}")
                lines.append(f"Status Text: {self._response_data.get('statusText', '')}")
                lines.append("")

                # response headers
                resp_headers = self._response_data.get("headers", {})
                if resp_headers:
                    lines.append("── Response Headers ──")
                    for k, v in resp_headers.items():
                        lines.append(f"  {k}: {v}")
                    lines.append("")

                # response body
                body = self._response_data.get("body", "")
                if body:
                    lines.append("── Response Body ──")
                    # try JSON pretty-print
                    try:
                        parsed = json.loads(body)
                        lines.append(json.dumps(parsed, indent=2))
                    except (json.JSONDecodeError, TypeError):
                        lines.append(body[:5000])
                else:
                    lines.append("[No response body]")

                textarea.load_text("\n".join(lines))
            else:
                textarea.load_text("No response yet -- click Send to replay the request.")

            self._set_active_tab("rtab-response")
            self._active_tab = "response"
        except NoMatches:
            pass

    def _set_active_tab(self, active_id: str) -> None:
        try:
            for btn in self.query("#replay-tabs Button"):
                btn.remove_class("active")
            self.query_one(f"#{active_id}", Button).add_class("active")
        except NoMatches:
            pass

    def _parse_headers_from_editor(self) -> dict[str, str]:
        """Parse header key: value pairs from the textarea."""
        headers = {}
        try:
            textarea = self.query_one("#replay-textarea", TextArea)
            for line in textarea.text.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ": " in line:
                    k, v = line.split(": ", 1)
                    headers[k.strip()] = v.strip()
                elif ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
        except NoMatches:
            pass
        return headers

    def _get_body_from_editor(self) -> str:
        """Get the body text if we're on the body tab."""
        if self._active_tab == "body":
            try:
                return self.query_one("#replay-textarea", TextArea).text
            except NoMatches:
                pass
        elif self._original_request and self._original_request.request_body:
            return self._original_request.request_body
        return ""

    def set_response(self, data: dict) -> None:
        """Called by the app with the replay response data."""
        self._response_data = data
        self._show_response_tab()

        try:
            status_code = data.get("status", 0)
            style_word = "green" if 200 <= status_code < 300 else "red" if status_code >= 400 else "yellow"
            self.query_one("#replay-status-label", Label).update(
                f"Response: {status_code} {data.get('statusText', '')}"
            )
        except NoMatches:
            pass

    # ── Events ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id == "replay-method":
            # cycle through HTTP methods
            current = event.button.label
            try:
                idx = HTTP_METHODS.index(str(current))
            except ValueError:
                idx = 0
            next_idx = (idx + 1) % len(HTTP_METHODS)
            event.button.label = HTTP_METHODS[next_idx]

        elif btn_id == "replay-send":
            self._do_send()

        elif btn_id == "replay-close":
            self.hide()

        elif btn_id == "rtab-headers":
            self._show_headers_tab()

        elif btn_id == "rtab-body":
            self._show_body_tab()

        elif btn_id == "rtab-response":
            self._show_response_tab()

    def _do_send(self) -> None:
        """Gather request params and invoke the replay callback."""
        if not self._replay_callback:
            return

        try:
            method = str(self.query_one("#replay-method", Button).label)
            url = self.query_one("#replay-url", Input).value.strip()
        except NoMatches:
            return

        if not url:
            return

        # save current headers if on headers tab
        headers = self._parse_headers_from_editor() if self._active_tab == "headers" else (
            self._original_request.request_headers if self._original_request else {}
        )
        body = self._get_body_from_editor()

        try:
            self.query_one("#replay-status-label", Label).update(f"Sending {method} {url[:50]}...")
        except NoMatches:
            pass

        # invoke async callback (app wires this up)
        self._replay_callback(method, url, headers, body)
