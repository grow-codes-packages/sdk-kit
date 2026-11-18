// Created by sdk-kit __SDK_KIT_VERSION__; owned by this repository.
//! Basics of the __DISPLAY__ Rust SDK: configuration from the environment, health, an
//! authenticated ping, hooks and error handling.
//!
//! ```sh
//! GROW___KEY_UPPER___URL=http://127.0.0.1:__PORT__ GROW___KEY_UPPER___TOKEN=... cargo run
//! ```

use std::sync::Arc;

use grow___KEY_SNAKE__ as sdk;
use sdk::core::{ErrorInfo, Hooks};
use sdk::ErrorCode;

use sdk::__SERVICE__Client as Client;
use sdk::__SERVICE__Config as Config;

/// Prints every retry.
struct RetryLogger;

impl Hooks for RetryLogger {
    fn on_error(&self, info: &ErrorInfo) {
        if info.will_retry {
            eprintln!(
                "retrying {} {} (attempt {})",
                info.method, info.url, info.attempt
            );
        }
    }
}

#[tokio::main]
async fn main() {
    if let Err(err) = run().await {
        eprintln!("error [{}]: {err}", err.code());
        std::process::exit(1);
    }
}

async fn run() -> sdk::Result<()> {
    // explicit > GROW___KEY_UPPER___* > vendor variables > defaults; invalid values name the
    // variable, never its value.
    let config = Config::builder()
        .hooks(Arc::new(RetryLogger))
        .build_from_env()?;
    println!("config: {config:?}"); // credentials print as [REDACTED]

    let client = Client::new(config)?;
    let health = client.health().await?; // never fails for an unreachable service
    println!("health: {} ({})", health.healthy, health.status);

    match client.ping().await {
        Ok(latency) => println!("ping: {} ms", latency.as_millis()),
        Err(e) if e.code() == ErrorCode::Authentication => {
            println!("ping: check GROW___KEY_UPPER___TOKEN ({e})")
        }
        Err(e) => return Err(e),
    }
    match client.server_version().await {
        Ok(version) => println!("server version: {version}"),
        Err(e) if e.code() == ErrorCode::Unsupported => println!("server version: not exposed"),
        Err(e) => return Err(e),
    }
    client.close().await;
    Ok(())
}
