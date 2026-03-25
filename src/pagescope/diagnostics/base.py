"""Abstract base class for all diagnostic modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Generic, TypeVar

from playwright.async_api import CDPSession, Page
from pydantic import BaseModel

from pagescope.models.common import SessionConfig

TReport = TypeVar("TReport", bound=BaseModel)
TEvent = TypeVar("TEvent", bound=BaseModel)


class BaseDiagnostic(ABC, Generic[TReport, TEvent]):
    """Abstract base for all diagnostic modules.

    Each module:
    1. Enables required CDP domains during setup()
    2. Collects data via CDP events and/or Playwright APIs
    3. Produces a structured Pydantic report via analyze()
    4. Optionally supports real-time streaming via stream()
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        self._page = page
        self._cdp = cdp
        self._config = config
        self._enabled = False

    @abstractmethod
    async def setup(self) -> None:
        """Enable required CDP domains and register event listeners."""
        ...

    @abstractmethod
    async def analyze(self) -> TReport:
        """Run the diagnostic and return a structured report."""
        ...

    async def stream(self) -> AsyncIterator[TEvent]:
        """Yield diagnostic events in real time. Override in subclasses."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")
        yield  # type: ignore[misc]

    async def teardown(self) -> None:
        """Disable CDP domains and clean up."""
        self._enabled = False
