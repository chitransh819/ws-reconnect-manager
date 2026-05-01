"""Reliable asyncio WebSocket clients with reconnect and heartbeat support."""

from .client import ReconnectingWebSocketClient
from .exceptions import (
    DeadConnectionError,
    DoNotReconnect,
    HeartbeatError,
    NotConnected,
    ReconnectExhausted,
    WebSocketReconnectError,
)
from .policies import Heartbeat, ReconnectPolicy

__all__ = [
    "DeadConnectionError",
    "DoNotReconnect",
    "Heartbeat",
    "HeartbeatError",
    "NotConnected",
    "ReconnectExhausted",
    "ReconnectPolicy",
    "ReconnectingWebSocketClient",
    "WebSocketReconnectError",
]
