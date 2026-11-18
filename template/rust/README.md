# grow-__KEY__ (Rust)

Rust SDK for __DISPLAY__ by [Grow Codes](https://grow.codes). Async on tokio, with an optional
blocking client.

```toml
[dependencies]
grow-__KEY__ = "__VERSION__"
# blocking client:   features = ["blocking"]
# test fakes/runner: features = ["testing"] (dev-dependency)
```

```rust,no_run
use grow___KEY_SNAKE__::{__SERVICE__Client, __SERVICE__Config};

#[tokio::main]
async fn main() -> grow___KEY_SNAKE__::Result<()> {
    // explicit > GROW___KEY_UPPER___* > vendor variables > defaults
    let client = __SERVICE__Client::new(__SERVICE__Config::from_env()?)?;
    println!("{:?}", client.health().await?);
    client.close().await;
    Ok(())
}
```

- Errors: one `Error` enum with `code()`, `http_status()`, `request_id()`, `is_retryable()`,
  `retry_after()`; messages never contain credentials.
- Retries with full-jitter backoff and `Retry-After`, connect/request/total timeouts,
  cancellation (drop the future or pass a `CancellationToken`), request hooks, `tracing` debug
  events.
- MSRV 1.85. Licence Apache-2.0. Documentation: https://grow-codes-packages.github.io/__KEY__/

Development: `make deps build lint test coverage license pack docs` (see `Makefile`).
