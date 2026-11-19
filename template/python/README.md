# grow-__KEY__ (Python)

Python SDK for [__DISPLAY__](https://grow-codes-packages.github.io/__KEY__/) by Grow Codes.
Unofficial and community maintained; "__DISPLAY__" is a trademark of __VENDOR__.

```bash
pip install grow-__KEY__
```

```python
from grow___KEY_SNAKE__ import __SERVICE__Client, __SERVICE__Config

# Reads GROW___KEY_UPPER___URL, GROW___KEY_UPPER___TOKEN, ... from the environment.
with __SERVICE__Client.from_env() as client:
    print(client.health())
    print(client.server_version())
```

The async client has the same methods:

```python
import asyncio
from grow___KEY_SNAKE__ import Async__SERVICE__Client

async def main() -> None:
    async with Async__SERVICE__Client.from_env() as client:
        print(await client.health())

asyncio.run(main())
```

- Python 3.10 or newer, typed (`py.typed`), `httpx` based, environment proxies ignored unless
  configured.
- Retries with full-jitter backoff and `Retry-After`, connect/request/total timeouts,
  cancellation, hooks and a silent-by-default `logging` logger named `grow___KEY_SNAKE__`.
- Credentials are wrapped in `Secret` and never appear in `repr()`, logs or error messages.
- `grow___KEY_SNAKE__.testing` ships in-memory fakes and the conformance runner.

Documentation: https://grow-codes-packages.github.io/__KEY__/ ·
Source: https://github.com/grow-codes-packages/__KEY__ · Licence: Apache-2.0
