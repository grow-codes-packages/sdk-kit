# Python examples

Install the package, point it at a running __DISPLAY__ and run an example:

```bash
pip install grow-__KEY__
export GROW___KEY_UPPER___URL=http://127.0.0.1:__PORT__
export GROW___KEY_UPPER___TOKEN=...   # when the service needs one
python examples/python/basic.py
```

| File | Shows |
| - | - |
| `basic.py` | sync client: health, ping, server version, error handling |
| `async_basic.py` | async client, cancellation by task |
| `hooks_and_logging.py` | request hooks, the `grow___KEY_SNAKE__` logger, retries and timeouts |
<!-- @sdk-kit:if secrets -->
| `secrets_cache.py` | cached secret reads, typed getters, `load_env`, `watch` (in-memory provider) |
<!-- @sdk-kit:endif -->
