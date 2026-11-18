// Skeleton created by sdk-kit __SDK_KIT_VERSION__; owned by this repository (edit freely).
//! # grow-__KEY__
//!
//! Rust SDK for [__DISPLAY__](https://grow-codes-packages.github.io/__KEY__/) by Grow Codes.
//!
//! ```no_run
//! # async fn demo() -> grow___KEY_SNAKE__::Result<()> {
//! use grow___KEY_SNAKE__::{__SERVICE__Client, __SERVICE__Config};
//!
//! let client = __SERVICE__Client::new(__SERVICE__Config::from_env()?)?;
//! let health = client.health().await?;
//! println!("healthy: {}", health.healthy);
//! client.close().await;
//! # Ok(())
//! # }
//! ```
//!
//! Features: `blocking` (a blocking client), `testing` (in-memory fakes and the conformance
//! runner)
// @sdk-kit:if logging
//! , `tracing-layer` and `log-bridge` (logging adapters, on by default)
// @sdk-kit:endif
// @sdk-kit:if tracing
//! , `tower` and `reqwest-middleware` (tracing instrumentation)
// @sdk-kit:endif
//! .
#![cfg_attr(docsrs, feature(doc_cfg))]

pub mod core;

mod client;
mod config;

#[cfg(feature = "blocking")]
#[cfg_attr(docsrs, doc(cfg(feature = "blocking")))]
pub mod blocking;

#[cfg(feature = "testing")]
#[cfg_attr(docsrs, doc(cfg(feature = "testing")))]
pub mod testing;

// @sdk-kit:if logging
pub mod logging;
// @sdk-kit:endif
// @sdk-kit:if secrets
pub mod secrets;
// @sdk-kit:endif
// @sdk-kit:if tracing
pub mod tracing;
// @sdk-kit:endif

pub use crate::core::{Error, ErrorCode, HealthStatus, Result, RetryPolicy, Secret};

pub use crate::config::DEFAULT_URL;

pub use crate::client::__SERVICE__Client;

pub use crate::config::__SERVICE__Config;

pub use crate::config::__SERVICE__ConfigBuilder;

/// Service-prefixed alias of [`Error`].
pub type __SERVICE__Error = Error;
