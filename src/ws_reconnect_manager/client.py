"""A reconnecting aiohttp WebSocket client."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from types import TracebackType
from typing import Any, Protocol, Self

from aiohttp import (
    ClientError,
    ClientSession,
    ClientWebSocketResponse,
    WSMessage,
    WSMsgType,
    WSServerHandshakeError,
)

from .exceptions import (
    DeadConnectionError,
    DoNotReconnect,
    HeartbeatError,
    NotConnected,
    ReconnectExhausted,
)
from .policies import Heartbeat, ReconnectPolicy

MessageHandler = Callable[[WSMessage, ClientWebSocketResponse], Awaitable[None] | None]
LifecycleHandler = Callable[["ReconnectingWebSocketClient"], Awaitable[None] | None]
ErrorHandler = Callable[[BaseException, "ReconnectingWebSocketClient"], Awaitable[None] | None]
RetryHandler = Callable[[BaseException, int, float, "ReconnectingWebSocketClient"], Awaitable[None] | None]
HeaderFactory = Mapping[str, str] | Callable[[], Mapping[str, str] | Awaitable[Mapping[str, str]]]


class Connector(Protocol):
    def __call__(
        self,
        session: ClientSession,
        url: str,
        *,
        headers: Mapping[str, str] | None,
        **kwargs: Any,
    ) -> Any:
        ...


class ReconnectingWebSocketClient:
    """Async WebSocket client with reconnect, heartbeat, and dead socket checks."""

    def __init__(
        self,
        url: str,
        *,
        headers: HeaderFactory | None = None,
        heartbeat: Heartbeat | None = None,
        reconnect: ReconnectPolicy | None = None,
        heartbeat_interval: float | None = None,
        heartbeat_payload: Any = None,
        dead_timeout: float = 20.0,
        session: ClientSession | None = None,
        connector: Connector | None = None,
        logger: logging.Logger | None = None,
        **ws_options: Any,
    ) -> None:
        self.url = url
        self.headers = headers
        if heartbeat is None:
            heartbeat = Heartbeat(heartbeat_interval, heartbeat_payload)
        self.heartbeat = heartbeat
        self.reconnect = reconnect or ReconnectPolicy()
        self.dead_timeout = dead_timeout
        self._session = session
        self._owns_session = session is None
        self._connector = connector or _default_connector
        self._ws_options = ws_options
        self._logger = logger or logging.getLogger(__name__)
        self._ws: ClientWebSocketResponse | None = None
        self._stopped = asyncio.Event()
        self._connected = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def websocket(self) -> ClientWebSocketResponse | None:
        return self._ws

    def stop(self) -> None:
        self._stopped.set()
        if self._ws is not None and not self._ws.closed:
            asyncio.create_task(self._ws.close())

    async def wait_connected(self) -> None:
        await self._connected.wait()

    async def send_json(self, payload: Any) -> None:
        ws = self._require_ws()
        await ws.send_json(payload)

    async def send_str(self, payload: str) -> None:
        ws = self._require_ws()
        await ws.send_str(payload)

    async def send_bytes(self, payload: bytes) -> None:
        ws = self._require_ws()
        await ws.send_bytes(payload)

    async def run(
        self,
        *,
        on_before_connect: LifecycleHandler | None = None,
        on_message: MessageHandler | None = None,
        on_connect: LifecycleHandler | None = None,
        on_disconnect: ErrorHandler | None = None,
        on_reconnect: RetryHandler | None = None,
        on_dead: ErrorHandler | None = None,
        on_fatal: ErrorHandler | None = None,
    ) -> None:
        """Run until ``stop()`` is called or reconnecting is no longer allowed."""

        attempt = 0
        async with self._session_context() as session:
            while not self._stopped.is_set():
                try:
                    await _maybe_await(on_before_connect, self)
                    await self._connect_once(
                        session,
                        on_message=on_message,
                        on_connect=on_connect,
                    )
                    attempt = 0
                except DoNotReconnect as exc:
                    await _maybe_await(on_fatal, exc, self)
                    raise
                except _RETRYABLE_ERRORS as exc:
                    self._connected.clear()
                    await _maybe_await(on_disconnect, exc, self)
                    if isinstance(exc, DeadConnectionError):
                        await _maybe_await(on_dead, exc, self)
                    if self._stopped.is_set():
                        return
                    if not self.reconnect.can_retry(attempt):
                        exhausted = ReconnectExhausted(
                            f"reconnect attempts exhausted after {attempt} retries"
                        )
                        await _maybe_await(on_fatal, exhausted, self)
                        raise exhausted from exc
                    delay = self.reconnect.delay_for(attempt)
                    await _maybe_await(on_reconnect, exc, attempt + 1, delay, self)
                    self._logger.info(
                        "websocket reconnecting",
                        extra={"attempt": attempt + 1, "delay": delay, "url": self.url},
                    )
                    attempt += 1
                    await _sleep_or_stop(delay, self._stopped)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    async def _connect_once(
        self,
        session: ClientSession,
        *,
        on_message: MessageHandler | None,
        on_connect: LifecycleHandler | None,
    ) -> None:
        headers = await self._resolve_headers()
        async with self._connector(
            session,
            self.url,
            headers=headers,
            **self._ws_options,
        ) as ws:
            self._ws = ws
            self._connected.set()
            await _maybe_await(on_connect, self)
            try:
                await self._receive_loop(ws, on_message)
            finally:
                self._connected.clear()
                self._ws = None

    async def _receive_loop(
        self,
        ws: ClientWebSocketResponse,
        on_message: MessageHandler | None,
    ) -> None:
        heartbeat_task = (
            asyncio.create_task(self._send_heartbeats(ws))
            if self.heartbeat.enabled
            else None
        )
        try:
            while not self._stopped.is_set():
                receive_task = asyncio.create_task(ws.receive(timeout=self.dead_timeout))
                wait_for = {receive_task}
                if heartbeat_task is not None:
                    wait_for.add(heartbeat_task)
                done, pending = await asyncio.wait(
                    wait_for,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if heartbeat_task is not None and heartbeat_task in done:
                    receive_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await receive_task
                    exc = heartbeat_task.exception()
                    raise HeartbeatError("heartbeat task stopped") from exc

                message = receive_task.result()
                await self._handle_message(message, ws, on_message)
        except TimeoutError as exc:
            raise DeadConnectionError(
                f"no websocket frames received for {self.dead_timeout:g} seconds"
            ) from exc
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

    async def _handle_message(
        self,
        message: WSMessage,
        ws: ClientWebSocketResponse,
        on_message: MessageHandler | None,
    ) -> None:
        if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING}:
            raise ConnectionResetError("websocket closed")
        if message.type is WSMsgType.ERROR:
            raise ConnectionResetError(f"websocket error: {ws.exception()!r}")
        await _maybe_await(on_message, message, ws)

    async def _send_heartbeats(self, ws: ClientWebSocketResponse) -> None:
        while not self._stopped.is_set():
            await asyncio.sleep(self.heartbeat.interval or 0)
            payload = self.heartbeat.next_payload()
            if payload is None:
                await ws.ping()
            elif isinstance(payload, str):
                await ws.send_str(payload)
            elif isinstance(payload, bytes):
                await ws.send_bytes(payload)
            else:
                await ws.send_json(payload)

    async def _resolve_headers(self) -> Mapping[str, str] | None:
        if self.headers is None or isinstance(self.headers, Mapping):
            return self.headers
        headers = self.headers()
        if isinstance(headers, Awaitable):
            return await headers
        return headers

    def _require_ws(self) -> ClientWebSocketResponse:
        if self._ws is None or self._ws.closed:
            raise NotConnected("websocket is not connected")
        return self._ws

    @asynccontextmanager
    async def _session_context(self):
        if self._session is not None:
            yield self._session
            return
        async with ClientSession() as session:
            yield session


async def _maybe_await(func: Callable[..., Any] | None, *args: Any) -> Any:
    if func is None:
        return None
    result = func(*args)
    if isinstance(result, Awaitable):
        return await result
    return result


async def _sleep_or_stop(delay: float, stopped: asyncio.Event) -> None:
    if delay <= 0:
        return
    with suppress(TimeoutError):
        await asyncio.wait_for(stopped.wait(), timeout=delay)


def _default_connector(
    session: ClientSession,
    url: str,
    *,
    headers: Mapping[str, str] | None,
    **kwargs: Any,
) -> Any:
    return session.ws_connect(url, headers=headers, **kwargs)


_RETRYABLE_ERRORS = (
    asyncio.TimeoutError,
    ClientError,
    ConnectionResetError,
    DeadConnectionError,
    HeartbeatError,
    OSError,
    WSServerHandshakeError,
)
