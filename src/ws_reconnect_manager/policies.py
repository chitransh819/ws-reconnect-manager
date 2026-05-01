"""Configuration policies for reconnecting WebSocket clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import uniform
from typing import Any

HeartbeatPayload = Any | Callable[[], Any]


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """Heartbeat settings.

    Set ``interval`` to ``None`` or ``0`` to disable heartbeat sends. ``payload``
    may be a static value or a zero-argument callable returning the next value.
    """

    interval: float | None = 15.0
    payload: HeartbeatPayload = None

    @property
    def enabled(self) -> bool:
        return self.interval is not None and self.interval > 0

    def next_payload(self) -> Any:
        return self.payload() if callable(self.payload) else self.payload


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Exponential backoff policy for reconnect attempts."""

    initial_delay: float = 1.0
    max_delay: float = 60.0
    factor: float = 2.0
    jitter: float = 0.2
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be >= 0")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")
        if self.factor < 1:
            raise ValueError("factor must be >= 1")
        if self.jitter < 0:
            raise ValueError("jitter must be >= 0")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def can_retry(self, attempt: int) -> bool:
        return self.max_attempts is None or attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        delay = min(self.max_delay, self.initial_delay * (self.factor ** attempt))
        if self.jitter == 0 or delay == 0:
            return delay
        spread = delay * self.jitter
        return max(0.0, delay + uniform(-spread, spread))
