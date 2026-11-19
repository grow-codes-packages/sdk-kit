# Grow Codes SDK for __DISPLAY__

[![CI](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml/badge.svg)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/grow-codes-packages/__KEY__?sort=semver)](https://github.com/grow-codes-packages/__KEY__/releases)
[![Docs](https://img.shields.io/badge/docs-grow--codes--packages.github.io-blue)](https://grow-codes-packages.github.io/__KEY__/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Grow Codes](https://img.shields.io/badge/Grow%20Codes-grow.codes-2ea44f)](https://grow.codes)

| Language | Package | Coverage |
| - | - | - |
| TypeScript | [![npm](https://img.shields.io/npm/v/@grow-codes/__KEY__)](https://www.npmjs.com/package/@grow-codes/__KEY__) | [![TypeScript coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-typescript.json)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml) |
| Rust | [![crates.io](https://img.shields.io/crates/v/grow-__KEY__)](https://crates.io/crates/grow-__KEY__) [![docs.rs](https://img.shields.io/docsrs/grow-__KEY__)](https://docs.rs/grow-__KEY__) | [![Rust coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-rust.json)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml) |
| Go | [![Go Reference](https://pkg.go.dev/badge/github.com/grow-codes-packages/__KEY__/go.svg)](https://pkg.go.dev/github.com/grow-codes-packages/__KEY__/go) | [![Go coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-go.json)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml) |
| Python | [![PyPI](https://img.shields.io/pypi/v/grow-__KEY__)](https://pypi.org/project/grow-__KEY__/) | [![Python coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-python.json)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml) |
| Java | [![Maven Central](https://img.shields.io/maven-central/v/codes.grow.packages/__KEY__)](https://central.sonatype.com/artifact/codes.grow.packages/__KEY__) | [![Java coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-java.json)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml) |

Open-source client libraries for [__DISPLAY__](#trademarks-and-disclaimer) in **TypeScript, Rust, Go,
Python and Java** — one API, five idiomatic packages, tested against a real __DISPLAY__ in Docker.

- **Typed client** with timeouts, retries with jitter, `Retry-After`, cancellation and one error
  model (`__SERVICE__Error` with canonical codes) in every language.
- **Secrets stay secret**: credentials are redacted in `toString`, logs, hooks and error messages.
<!-- @sdk-kit:if secrets -->
- **Secrets**: read, write, list and delete secrets, typed getters, `loadEnv`, change watching and a
  TTL cache with refresh-ahead.
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if logging -->
- **Logging**: batched, compressed log shipping with back-pressure, redaction, a logger facade and
  adapters for the common logging frameworks of each language; log search where __DISPLAY__ offers it.
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if tracing -->
- **Tracing**: OpenTelemetry setup in one call, span helpers, context propagation, framework
  middleware and a trace query client.
<!-- @sdk-kit:endif -->

## Contents

- [Supported service version](#supported-service-version)
- [Install](#install)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Function overview](#function-overview)
- [Testing with Docker](#testing-with-docker)
- [Compatibility](#compatibility)
- [Contributing](#contributing)
- [Security](#security)
- [Licence](#licence)
- [Trademarks and disclaimer](#trademarks-and-disclaimer)
- [About Grow Codes](#about-grow-codes)

## Supported service version

Tested in CI against **`__IMAGE__`** (the version pinned in the Grow Codes stack catalog). Other
versions with the same API usually work; see [Compatibility](#compatibility) and
[docs/compatibility.md](docs/compatibility.md).

## Install

| Language | Package | Install |
| - | - | - |
| TypeScript (Node.js ≥ 22.12) | `@grow-codes/__KEY__` | `npm install @grow-codes/__KEY__` |
| Rust (MSRV 1.88) | `grow-__KEY__` | `cargo add grow-__KEY__` |
| Go (1.26+) | `github.com/grow-codes-packages/__KEY__/go` | `go get github.com/grow-codes-packages/__KEY__/go` |
| Python (≥ 3.10) | `grow-__KEY__` | `pip install grow-__KEY__` |
| Java (17+) | `codes.grow.packages:__KEY__` | see below |

Maven:

```xml
<dependency>
  <groupId>codes.grow.packages</groupId>
  <artifactId>__KEY__</artifactId>
  <version>__VERSION__</version>
</dependency>
```

Gradle (Kotlin DSL):

```kotlin
implementation("codes.grow.packages:__KEY__:__VERSION__")
```

## Quickstart

Every package reads its configuration from the environment (`GROW___KEY_UPPER___URL`,
`GROW___KEY_UPPER___TOKEN`, …, see [Configuration](#configuration)) or from an explicit config
object. The examples check the service health and make one authenticated call.

### TypeScript

```ts
import { __SERVICE__Client } from "@grow-codes/__KEY__";

const client = __SERVICE__Client.fromEnv();
try {
  const health = await client.health();
  console.log(health.healthy, health.status);
  console.log("latency ms:", await client.ping());
} finally {
  await client.close();
}
```

### Rust

```rust
use grow___KEY_SNAKE__::__SERVICE__Client;

#[tokio::main]
async fn main() -> Result<(), grow___KEY_SNAKE__::Error> {
    let client = __SERVICE__Client::from_env()?;
    let health = client.health().await?;
    println!("{} {}", health.healthy, health.status);
    println!("latency: {:?}", client.ping().await?);
    client.close().await;
    Ok(())
}
```

### Go

```go
package main

import (
	"context"
	"fmt"
	"log"

	__PKG__ "github.com/grow-codes-packages/__KEY__/go"
)

func main() {
	ctx := context.Background()
	client, err := __PKG__.NewClientFromEnv()
	if err != nil {
		log.Fatal(err)
	}
	defer client.Close()

	health, err := client.Health(ctx)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(health.Healthy, health.Status)
}
```

### Python

```python
from grow___KEY_SNAKE__ import __SERVICE__Client

with __SERVICE__Client.from_env() as client:
    health = client.health()
    print(health.healthy, health.status)
    print("latency ms:", client.ping())
```

Async code uses `Async__SERVICE__Client` with the same methods (`async with`, `await client.health()`).

### Java

```java
import codes.grow.packages.__PKG__.__SERVICE__Client;

try (__SERVICE__Client client = __SERVICE__Client.fromEnv()) {
    var health = client.health();
    System.out.println(health.healthy() + " " + health.status());
    System.out.println("latency ms: " + client.ping());
}
```

More complete programs live in [examples/](examples/) — one folder per language.

## Configuration

All settings can be passed in code or through environment variables. Precedence: **explicit value >
`GROW___KEY_UPPER___*` variable > vendor variable > default.** A present but invalid value raises a
`ConfigError` that names the variable (never its value).

| Setting | Environment variable | Default |
| - | - | - |
| `url` | `GROW___KEY_UPPER___URL` | service default |
| `token` | `GROW___KEY_UPPER___TOKEN` | none |
| `connectTimeout` | `GROW___KEY_UPPER___CONNECT_TIMEOUT` | 10 s |
| `requestTimeout` (per attempt) | `GROW___KEY_UPPER___REQUEST_TIMEOUT` | 30 s |
| `totalTimeout` (including retries) | `GROW___KEY_UPPER___TOTAL_TIMEOUT` | 120 s |
| `retry.maxRetries` | `GROW___KEY_UPPER___MAX_RETRIES` | 3 |
| `tls.caCertPath` | `GROW___KEY_UPPER___CA_CERT` | system roots |
| `tls.clientCertPath` / `tls.clientKeyPath` | `GROW___KEY_UPPER___CLIENT_CERT` / `GROW___KEY_UPPER___CLIENT_KEY` | none |
| `tls.insecureSkipVerify` (tests only) | `GROW___KEY_UPPER___INSECURE_SKIP_VERIFY` | `false` |
| `proxy` | `GROW___KEY_UPPER___PROXY` | none (environment proxies are ignored) |
| `headers`, `userAgentSuffix`, `hooks`, `logger` | — | none |

Vendor variables that are also read: __ENV__.

Durations accept milliseconds (`1500`) or units (`500ms`, `10s`, `1m30s`); booleans accept
`true/false/1/0/yes/no/on/off`. Field names follow each language's convention
(`request_timeout` in Python and Rust, `RequestTimeout` in Go). The full reference is in the
[documentation](https://grow-codes-packages.github.io/__KEY__/).

## Function overview

<!-- service:function-overview — the service fills this section; keep the heading. -->

The same functions exist in every language, named per language convention (`getString` in
TypeScript and Java, `get_string` in Python and Rust, `GetString` in Go).

| Area | Functions | Description |
| - | - | - |
| Client | `health`, `ping`, `serverVersion`, `close` | liveness, authenticated round trip, server version, shutdown |
<!-- @sdk-kit:if secrets -->
| Secrets | `get`, `getString`, `getJson`, `getNumber`, `getBool`, `require`, `exists`, `getMany`, `getAll`, `list`, `set`, `delete`, `metadata`, `loadEnv`, `watch` | secrets provider API, plus `SecretCache` |
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if logging -->
| Logging | `send`, `sendBatch`, `flush`, `close`, `stats`, `logger`, `search`, `tail`, `listStreams`, `listLabels`, `waitForLog` | log shipping and querying |
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if tracing -->
| Tracing | `initTracing`, `withSpan`, `traced`, `inject`, `extract`, `getTrace`, `searchTraces`, `listServices`, `listOperations`, `getDependencies`, `waitForTrace` | OpenTelemetry setup and trace queries |
<!-- @sdk-kit:endif -->

<!-- /service:function-overview -->

## Testing with Docker

The integration suite runs every public function against a real __DISPLAY__ (`__IMAGE__`) in Docker.
Each language package is packed and installed into a separate consumer project first, so the tests
use the package exactly as you would.

```sh
make test-docker                     # all five languages
make test-docker LANGS="go python"   # a subset
```

No host ports are published and every run uses its own Compose project, so runs never collide; the
stack is always removed afterwards (`docker compose down -v`). Unit tests need no Docker:
`make test` or `make coverage`.

## Compatibility

| | TypeScript | Rust | Go | Python | Java |
| - | - | - | - | - | - |
| Runtime | Node.js ≥ 22.12, ESM + CJS | stable, MSRV 1.88 | 1.26, 1.27 | 3.10 – 3.14 | 17, 21, 25 |
| Async | `Promise` + `AbortSignal` | `async` (tokio), `blocking` feature | `context.Context` | sync + `asyncio` | sync + `CompletableFuture` |
| __DISPLAY__ | `__IMAGE__` | `__IMAGE__` | `__IMAGE__` | `__IMAGE__` | `__IMAGE__` |

Functions that __DISPLAY__ (or its emulator) cannot serve are listed with the reason in
[docs/compatibility.md](docs/compatibility.md).

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[AGENTS.md](AGENTS.md) first. All five languages keep the same API; a change lands in all of them
together. Parts of this repository are generated by
[sdk-kit](https://github.com/grow-codes-packages/sdk-kit) and changed there.

## Security

Please report vulnerabilities privately to [opensource@grow.codes](mailto:opensource@grow.codes).
See [SECURITY.md](SECURITY.md).

## Licence

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attributions.

## Trademarks and disclaimer

This is an independent, community-maintained project. It is **not affiliated with, endorsed or
sponsored by its owner (__VENDOR__)**. __DISPLAY__ is a trademark of __VENDOR__; it is used here only to name the
service this SDK connects to. The __DISPLAY__ server is licensed separately by its owner
(__UPSTREAM_LICENSE__).

The software is provided "AS IS", without warranties or conditions of any kind. Grow Codes is not
responsible for any damage, data loss, security incident, outage or cost that results from using it.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## About Grow Codes

This SDK is built and maintained by [Grow Codes](https://grow.codes). Grow Codes publishes the
client libraries it builds as open source in the
[grow-codes-packages](https://github.com/grow-codes-packages) organisation, generated from one
shared kit so that every service and every language behaves the same way. Learn more at
[grow.codes](https://grow.codes).
