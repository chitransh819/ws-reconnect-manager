# ws-reconnect-manager

`ws-reconnect-manager` is a reliable asyncio WebSocket client for long-running
apps, bots, dashboards, workers, and services that must stay connected.

It reconnects automatically, sends heartbeats, detects dead sockets, and exposes
small lifecycle hooks so your app can resubscribe or restore state after every
reconnect.

## Repository Details

Suggested GitHub repository name:

```text
ws-reconnect-manager
```

Suggested GitHub description:

```text
Reliable asyncio WebSocket client with auto-reconnect, heartbeat monitoring, and dead connection detection.
```

PyPI package name:

```text
ws-reconnect-manager
```

Python import name:

```python
import ws_reconnect_manager
```

## Features

- automatic reconnects with exponential backoff and jitter
- heartbeat sends using ping, text, bytes, or JSON payloads
- dead connection detection when the socket stops producing frames
- callback hooks for connect, message, disconnect, retry, dead socket, and fatal
  errors
- safe send helpers that raise `NotConnected` while reconnecting
- dynamic auth headers for refreshed tokens
- clean `DoNotReconnect` escape hatch for fatal protocol errors

## Install

```bash
pip install ws-reconnect-manager
```

For local development:

```bash
pip install -e ".[test]"
pytest
```

## Quick Start

```python
import asyncio

from ws_reconnect_manager import ReconnectingWebSocketClient


async def main() -> None:
    client = ReconnectingWebSocketClient(
        "wss://example.com/events",
        headers={"authorization": "Bearer token"},
        heartbeat_payload={"type": "ping"},
        heartbeat_interval=15,
        dead_timeout=20,
    )

    async def on_connect(client) -> None:
        await client.send_json({"type": "subscribe", "topic": "notifications"})

    async def on_message(message, ws) -> None:
        print(message.data)

    await client.run(on_connect=on_connect, on_message=on_message)


asyncio.run(main())
```

## Dynamic Auth Headers

Pass a function when tokens may refresh between reconnect attempts.

```python
async def headers():
    token = await load_fresh_token()
    return {"authorization": f"Bearer {token}"}


client = ReconnectingWebSocketClient(
    "wss://example.com/ws",
    headers=headers,
)
```

## Stop Reconnecting For Fatal Protocol Errors

Raise `DoNotReconnect` from a message handler when the server sends an
unrecoverable error.

```python
from ws_reconnect_manager import DoNotReconnect


async def on_message(message, ws) -> None:
    if message.type.name == "TEXT" and "invalid token" in message.data:
        raise DoNotReconnect("server rejected credentials")
```

## Manual Sends

The current connected socket is available through safe helpers. They raise
`NotConnected` if a reconnect is in progress.

```python
await client.send_json({"type": "subscribe", "topic": "room"})
await client.send_str("hello")
await client.send_bytes(b"hello")
```

## Configuration

```python
from ws_reconnect_manager import Heartbeat, ReconnectPolicy


client = ReconnectingWebSocketClient(
    "wss://example.com/ws",
    heartbeat=Heartbeat(interval=15, payload={"type": "ping"}),
    reconnect=ReconnectPolicy(
        initial_delay=1,
        max_delay=60,
        factor=2,
        jitter=0.2,
        max_attempts=None,
    ),
)
```

## How It Fits With Servers

This package focuses on the reconnecting client. Your server can be any
WebSocket server: Autowire, FastAPI, Starlette, Django Channels, aiohttp, or a
custom ASGI app. On reconnect, use `on_connect` to resubscribe or ask the server
for missed state.

For Autowire projects, pair this with Autowire's notification store so pending
messages are flushed when the reconnecting client comes back online.

## Project Structure

```text
ws-reconnect-manager/
  src/
    ws_reconnect_manager/
      client.py
      exceptions.py
      policies.py
      __init__.py
  tests/
  pyproject.toml
  README.md
  LICENSE
```

## Build And Publish

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## License

MIT
