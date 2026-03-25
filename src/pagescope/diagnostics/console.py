"""Console diagnostic module -- captures console messages, exceptions, and violations."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.common import SessionConfig
from pagescope.models.console import (
    ConsoleEntry,
    ConsoleEvent,
    ConsoleLevel,
    ConsoleReport,
    ConsoleSummary,
    ExceptionInfo,
    Violation,
)


class ConsoleMonitor(BaseDiagnostic[ConsoleReport, ConsoleEvent]):
    """Captures console output, unhandled exceptions, and browser violations.

    CDP domains used:
    - Runtime (consoleAPICalled, exceptionThrown)
    - Log (entryAdded for browser-level logs)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)
        self._entries: list[ConsoleEntry] = []
        self._exceptions: list[ExceptionInfo] = []
        self._violations: list[Violation] = []
        self._events: asyncio.Queue[ConsoleEvent] = asyncio.Queue()

    async def setup(self) -> None:
        if self._enabled:
            return
        await self._cdp.send("Runtime.enable")
        await self._cdp.send("Log.enable")
        self._enabled = True

        self._cdp.on("Runtime.consoleAPICalled", self._on_console_api)
        self._cdp.on("Runtime.exceptionThrown", self._on_exception)
        self._cdp.on("Log.entryAdded", self._on_log_entry)

    def _on_console_api(self, params: dict) -> None:
        args = params.get("args", [])
        text_parts = []
        for arg in args:
            val = arg.get("value")
            if val is not None:
                text_parts.append(str(val))
            else:
                desc = arg.get("description", arg.get("type", ""))
                text_parts.append(str(desc))

        level_str = params.get("type", "log")
        level_map = {
            "log": ConsoleLevel.LOG,
            "info": ConsoleLevel.INFO,
            "warning": ConsoleLevel.WARNING,
            "error": ConsoleLevel.ERROR,
            "debug": ConsoleLevel.DEBUG,
            "dir": ConsoleLevel.LOG,
            "table": ConsoleLevel.LOG,
            "trace": ConsoleLevel.LOG,
            "assert": ConsoleLevel.ERROR,
        }
        level = level_map.get(level_str, ConsoleLevel.LOG)

        # extract source location from stack trace if available
        stack = params.get("stackTrace", {})
        frames = stack.get("callFrames", [])
        url = ""
        line = None
        col = None
        if frames:
            url = frames[0].get("url", "")
            line = frames[0].get("lineNumber")
            col = frames[0].get("columnNumber")

        entry = ConsoleEntry(
            level=level,
            text=" ".join(text_parts),
            source="console-api",
            url=url,
            line_number=line,
            column_number=col,
            timestamp=params.get("timestamp", time.time() * 1000),
        )
        self._entries.append(entry)
        self._events.put_nowait(
            ConsoleEvent(type="message", entry=entry)
        )

    def _on_exception(self, params: dict) -> None:
        details = params.get("exceptionDetails", {})
        exception = details.get("exception", {})

        # build stack trace string
        stack_trace = ""
        st = details.get("stackTrace", {})
        if st:
            frames = st.get("callFrames", [])
            lines = []
            for f in frames:
                fn = f.get("functionName", "<anonymous>")
                u = f.get("url", "")
                ln = f.get("lineNumber", 0)
                cn = f.get("columnNumber", 0)
                lines.append(f"    at {fn} ({u}:{ln}:{cn})")
            stack_trace = "\n".join(lines)

        info = ExceptionInfo(
            message=exception.get("description", details.get("text", "Unknown error")),
            description=exception.get("className", ""),
            stack_trace=stack_trace,
            url=details.get("url", ""),
            line_number=details.get("lineNumber"),
            column_number=details.get("columnNumber"),
            timestamp=params.get("timestamp", time.time() * 1000),
        )
        self._exceptions.append(info)
        self._events.put_nowait(
            ConsoleEvent(type="exception", exception=info)
        )

    def _on_log_entry(self, params: dict) -> None:
        entry_data = params.get("entry", {})
        level_str = entry_data.get("level", "info")
        level_map = {
            "verbose": ConsoleLevel.VERBOSE,
            "info": ConsoleLevel.INFO,
            "warning": ConsoleLevel.WARNING,
            "error": ConsoleLevel.ERROR,
        }
        level = level_map.get(level_str, ConsoleLevel.INFO)

        # browser-level log entries that are violations
        source = entry_data.get("source", "")
        if source == "violation":
            violation = Violation(
                type=entry_data.get("text", ""),
                description=entry_data.get("text", ""),
                url=entry_data.get("url", ""),
                timestamp=entry_data.get("timestamp", 0),
            )
            self._violations.append(violation)
            self._events.put_nowait(
                ConsoleEvent(type="violation", violation=violation)
            )
            return

        entry = ConsoleEntry(
            level=level,
            text=entry_data.get("text", ""),
            source=source,
            url=entry_data.get("url", ""),
            line_number=entry_data.get("lineNumber"),
            timestamp=entry_data.get("timestamp", 0),
        )
        self._entries.append(entry)
        self._events.put_nowait(
            ConsoleEvent(type="message", entry=entry)
        )

    async def analyze(self) -> ConsoleReport:
        if not self._enabled:
            await self.setup()

        summary = ConsoleSummary(
            total_messages=len(self._entries),
            errors=sum(1 for e in self._entries if e.level == ConsoleLevel.ERROR),
            warnings=sum(1 for e in self._entries if e.level == ConsoleLevel.WARNING),
            exceptions=len(self._exceptions),
            violations=len(self._violations),
        )

        return ConsoleReport(
            entries=self._entries,
            exceptions=self._exceptions,
            violations=self._violations,
            summary=summary,
        )

    async def stream(self) -> AsyncIterator[ConsoleEvent]:
        if not self._enabled:
            await self.setup()
        while True:
            event = await self._events.get()
            yield event

    async def teardown(self) -> None:
        try:
            await self._cdp.send("Runtime.disable")
            await self._cdp.send("Log.disable")
        except Exception:
            pass
        await super().teardown()
