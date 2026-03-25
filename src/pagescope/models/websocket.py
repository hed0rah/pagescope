"""Pydantic models for WebSocket diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebSocketFrame(BaseModel):
    """A single WebSocket frame."""

    request_id: str = ""
    timestamp: float = 0
    direction: str = ""  # "sent" or "received"
    opcode: int = 1  # 1=text, 2=binary
    payload_data: str = ""
    payload_length: int = 0
    mask: bool = False


class WebSocketConnection(BaseModel):
    """A WebSocket connection with its frames."""

    request_id: str = ""
    url: str = ""
    status: str = "open"  # "open", "closed", "error"
    frames: list[WebSocketFrame] = Field(default_factory=list)
    created_at: float = 0
    closed_at: float | None = None
    initiator_url: str = ""

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def sent_count(self) -> int:
        return sum(1 for f in self.frames if f.direction == "sent")

    @property
    def received_count(self) -> int:
        return sum(1 for f in self.frames if f.direction == "received")

    @property
    def total_bytes(self) -> int:
        return sum(f.payload_length for f in self.frames)
