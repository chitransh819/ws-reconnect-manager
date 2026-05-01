# smart-api-limiter

`smart-api-limiter` is an async Python toolkit for both sides of API rate
control:

- client side: an `httpx` wrapper that queues outgoing calls, waits for rate
  limit capacity, retries transient failures, and respects `Retry-After`.
- server side: ASGI middleware that protects incoming endpoints with token
  buckets, `429` responses, and standard rate-limit headers.

Install one package, then import only the side your app needs.

## Features

- outgoing async API client powered by `httpx`
- client token-bucket throttling
- bounded request concurrency
- retry with exponential backoff and jitter
- `Retry-After` support
- incoming ASGI rate limiting middleware
- per-IP, per-user, per-API-key, or per-tenant limiting
- endpoint-specific limits and request costs
- `Retry-After` and `X-RateLimit-*` response headers
- framework-agnostic support for FastAPI, Starlette, Litestar, Autowire, and
  other ASGI apps

## Install

```bash
pip install smart-api-limiter
```

For local development:

```bash
pip install -e ".[test]"
pytest
```

## Client-Side Usage

```python
import asyncio

from smart_api_limiter import AsyncAPIClient, ClientRateLimitConfig, RetryConfig


async def main() -> None:
    async with AsyncAPIClient(
        base_url="https://api.example.com",
        rate_limit=ClientRateLimitConfig(rate=10, period=1, burst=10),
        retry=RetryConfig(max_attempts=4),
        max_concurrency=5,
    ) as api:
        response = await api.get("/v1/users", params={"limit": 50})
        response.raise_for_status()
        print(response.json())


asyncio.run(main())
```

Wrap an existing `httpx.AsyncClient`:

```python
import httpx

from smart_api_limiter import AsyncAPIClient


async with httpx.AsyncClient(base_url="https://api.example.com") as http:
    api = AsyncAPIClient(client=http)
    response = await api.post("/jobs", json={"name": "nightly-sync"})
```

## Server-Side Usage

```python
from smart_api_limiter import RateLimit, RateLimitMiddleware


app = RateLimitMiddleware(
    app,
    default_limit=RateLimit(rate=120, period=60),
)
```

## Endpoint-Specific Limits

```python
from smart_api_limiter import RateLimit, RateLimitMiddleware


def rule_for(scope):
    if scope["path"].startswith("/auth/login"):
        return RateLimit(rate=5, period=60)
    if scope["path"].startswith("/reports"):
        return RateLimit(rate=10, period=300)
    return RateLimit(rate=120, period=60)


app = RateLimitMiddleware(app, rule_for=rule_for)
```

## API-Key/User Aware Limits

```python
def key_for(scope):
    headers = dict(scope.get("headers") or [])
    api_key = headers.get(b"x-api-key")
    if api_key:
        return api_key.decode(errors="ignore")

    user = scope.get("user")
    if user:
        return f"user:{user['id']}"

    client = scope.get("client")
    return client[0] if client else "anonymous"


app = RateLimitMiddleware(app, key_for=key_for)
```

## Project Structure

```text
smart-api-limiter/
  src/
    smart_api_limiter/
      client/          # outgoing HTTP client wrapper
      limiter.py       # in-memory token bucket
      middleware.py    # ASGI middleware
      policies.py      # server-side policy objects
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
