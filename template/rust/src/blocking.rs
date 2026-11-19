// Skeleton created by sdk-kit __SDK_KIT_VERSION__; owned by this repository (edit freely).
//! Blocking wrapper (feature `blocking`). Each client owns a tokio runtime with one worker
//! thread, so background work (log batching, exports, watchers, retries' timers) keeps running
//! between blocking calls.
//!
//! Do not use it from inside an async runtime (calls would panic); use the async client there.

use std::future::Future;
use std::time::Duration;

use crate::core::{Error, HealthStatus, Result};
use crate::{__SERVICE__Client as AsyncClient, __SERVICE__Config};

/// Blocking client for __DISPLAY__ with the same methods as the async client.
#[derive(Debug)]
pub struct __SERVICE__Client {
    inner: AsyncClient,
    runtime: tokio::runtime::Runtime,
}

impl __SERVICE__Client {
    /// Creates a client from a configuration.
    pub fn new(config: __SERVICE__Config) -> Result<Self> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .thread_name("grow-__KEY__-blocking")
            .enable_all()
            .build()
            .map_err(|e| Error::config("cannot start the tokio runtime").with_source(e))?;
        let inner = {
            let _guard = runtime.enter();
            AsyncClient::new(config)?
        };
        Ok(__SERVICE__Client { inner, runtime })
    }

    /// Creates a client from the process environment.
    pub fn from_env() -> Result<Self> {
        Self::new(__SERVICE__Config::from_env()?)
    }

    /// The wrapped async client.
    pub fn async_client(&self) -> &AsyncClient {
        &self.inner
    }

    /// Runs a future of the async API to completion on this client's runtime.
    pub fn block_on<F: Future>(&self, future: F) -> F::Output {
        self.runtime.block_on(future)
    }

    /// See [`AsyncClient::health`].
    pub fn health(&self) -> Result<HealthStatus> {
        self.block_on(self.inner.health())
    }

    /// See [`AsyncClient::ping`].
    pub fn ping(&self) -> Result<Duration> {
        self.block_on(self.inner.ping())
    }

    /// See [`AsyncClient::server_version`].
    pub fn server_version(&self) -> Result<String> {
        self.block_on(self.inner.server_version())
    }

    /// See [`AsyncClient::close`]. Idempotent.
    pub fn close(&self) {
        self.block_on(self.inner.close());
    }
}

impl Drop for __SERVICE__Client {
    fn drop(&mut self) {
        self.inner.transport().close();
    }
}
