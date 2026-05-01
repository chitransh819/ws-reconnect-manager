from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import pytest
from aiohttp import WSMessage, WSMsgType

from ws_reconnect_manager import (
    DeadConnectionError,
    DoNotReconnect,
    Heartbeat,
    NotConnected,
    ReconnectPolicy,
    ReconnectingWebSocketClient,
)


class FakeWebSocket:
    def __init__(self, frames: list[Any]) -> None:
        self.frames = deque(frames)
        self.closed = False
        self.sent_json: list[Any] = []
        self.sent_str: list[str] = []
        self.sent_bytes: list[bytes] = []

    async def receive(self, timeout: float | None = None) -> WSMessage:
        frame = self.frames.popleft()
        if isinstance(frame, BaseException):
            raise frame
        if frame == "wait":
            await asyncio.sleep(timeout or 0)
            raise TimeoutError
        return frame

    async def send_json(self, payload: Any) -> None:
        self.sent_json.append(payload)

    async def send_str(self, payload: str) -> None:
        self.sent_str.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    async def ping(self) -> None:
        self.sent_bytes.append(b"PING")

    async def close(self) -> None:
        self.closed = True

    def exception(self) -> Exception | None:
        return None


def text(data: str) -> WSMessage:
    return WSMessage(WSMsgType.TEXT, data, None)


def closed() -> WSMessage:
    return WSMessage(WSMsgType.CLOSED, None, None)


def make_connector(sockets: list[FakeWebSocket]):
    attempts = {"count": 0}

    @asynccontextmanager
    async def connector(session, url, *, headers=None, **kwargs):
        attempts["count"] += 1
        yield sockets.pop(0)

    connector.attempts = attempts
    return connector


@pytest.mark.asyncio
async def test_reconnects_after_closed_socket() -> None:
    sockets = [
        FakeWebSocket([closed()]),
        FakeWebSocket([text("ok")]),
    ]
    connector = make_connector(sockets)
    seen: list[str] = []
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=connector,
        reconnect=ReconnectPolicy(initial_delay=0, jitter=0),
        heartbeat=Heartbeat(interval=None),
    )

    async def on_message(message, ws) -> None:
        seen.append(message.data)
        client.stop()

    await client.run(on_message=on_message)

    assert connector.attempts["count"] == 2
    assert seen == ["ok"]


@pytest.mark.asyncio
async def test_before_connect_runs_for_each_attempt() -> None:
    sockets = [
        FakeWebSocket([closed()]),
        FakeWebSocket([text("ok")]),
    ]
    calls = 0
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=make_connector(sockets),
        reconnect=ReconnectPolicy(initial_delay=0, jitter=0),
        heartbeat=Heartbeat(interval=None),
    )

    async def on_before_connect(client) -> None:
        nonlocal calls
        calls += 1

    async def on_message(message, ws) -> None:
        client.stop()

    await client.run(on_before_connect=on_before_connect, on_message=on_message)

    assert calls == 2


@pytest.mark.asyncio
async def test_dead_connection_invokes_callback_and_reconnects() -> None:
    sockets = [
        FakeWebSocket(["wait"]),
        FakeWebSocket([text("alive")]),
    ]
    dead: list[BaseException] = []
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=make_connector(sockets),
        reconnect=ReconnectPolicy(initial_delay=0, jitter=0),
        heartbeat=Heartbeat(interval=None),
        dead_timeout=0.001,
    )

    async def on_dead(exc, client) -> None:
        dead.append(exc)

    async def on_message(message, ws) -> None:
        client.stop()

    await client.run(on_message=on_message, on_dead=on_dead)

    assert isinstance(dead[0], DeadConnectionError)


@pytest.mark.asyncio
async def test_heartbeat_sends_payload() -> None:
    socket = FakeWebSocket(["wait"])
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=make_connector([socket]),
        reconnect=ReconnectPolicy(initial_delay=0, jitter=0, max_attempts=1),
        heartbeat=Heartbeat(interval=0.001, payload={"type": "ping"}),
        dead_timeout=0.005,
    )

    with pytest.raises(Exception):
        await client.run()

    assert socket.sent_json
    assert socket.sent_json[0] == {"type": "ping"}


@pytest.mark.asyncio
async def test_heartbeat_stays_alive_between_messages() -> None:
    socket = FakeWebSocket([text("one"), text("two")])
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=make_connector([socket]),
        heartbeat=Heartbeat(interval=10, payload={"type": "ping"}),
    )
    seen: list[str] = []

    async def on_message(message, ws) -> None:
        seen.append(message.data)
        if len(seen) == 2:
            client.stop()

    await client.run(on_message=on_message)

    assert seen == ["one", "two"]


@pytest.mark.asyncio
async def test_do_not_reconnect_stops_loop() -> None:
    connector = make_connector([FakeWebSocket([text("fatal")])])
    client = ReconnectingWebSocketClient(
        "wss://example.test",
        connector=connector,
        reconnect=ReconnectPolicy(initial_delay=0, jitter=0),
        heartbeat=Heartbeat(interval=None),
    )

    async def on_message(message, ws) -> None:
        raise DoNotReconnect("nope")

    with pytest.raises(DoNotReconnect):
        await client.run(on_message=on_message)

    assert connector.attempts["count"] == 1


@pytest.mark.asyncio
async def test_send_requires_connection() -> None:
    client = ReconnectingWebSocketClient("wss://example.test")

    with pytest.raises(NotConnected):
        await client.send_json({"x": 1})
