"""Exception types raised by ws-reconnect-manager."""


class WebSocketReconnectError(Exception):
    """Base class for client lifecycle failures."""


class DeadConnectionError(WebSocketReconnectError):
    """Raised when no frames arrive before the configured dead timeout."""


class HeartbeatError(WebSocketReconnectError):
    """Raised when the heartbeat task cannot send to the socket."""


class ReconnectExhausted(WebSocketReconnectError):
    """Raised when the reconnect policy has no remaining attempts."""


class NotConnected(WebSocketReconnectError):
    """Raised when a send is attempted while no socket is connected."""


class DoNotReconnect(WebSocketReconnectError):
    """Raise from callbacks to stop the reconnect loop permanently."""
