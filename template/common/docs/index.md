# __DISPLAY__ SDK

[![Grow Codes](https://img.shields.io/badge/Grow%20Codes-grow.codes-2ea44f)](https://grow.codes)
[![CI](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml/badge.svg)](https://github.com/grow-codes-packages/__KEY__/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](license.md)

One API for **__DISPLAY__** in five languages: TypeScript, Rust, Go, Python and Java. Every package
has the same functions, options, defaults, error codes and behaviour, tested against a real
`__IMAGE__` in Docker.

| Language | Package | Coverage |
| - | - | - |
| TypeScript | [`@grow-codes/__KEY__`](https://www.npmjs.com/package/@grow-codes/__KEY__) | ![TypeScript coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-typescript.json) |
| Rust | [`grow-__KEY__`](https://crates.io/crates/grow-__KEY__) | ![Rust coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-rust.json) |
| Go | [`github.com/grow-codes-packages/__KEY__/go`](https://pkg.go.dev/github.com/grow-codes-packages/__KEY__/go) | ![Go coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-go.json) |
| Python | [`grow-__KEY__`](https://pypi.org/project/grow-__KEY__/) | ![Python coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-python.json) |
| Java | [`codes.grow.packages:__KEY__`](https://central.sonatype.com/artifact/codes.grow.packages/__KEY__) | ![Java coverage](https://img.shields.io/endpoint?url=https://grow-codes-packages.github.io/__KEY__/badges/coverage-java.json) |

## What you get

- **Client** with health, authenticated ping and server version ([Client](client.md)).
- **Configuration** from code or `GROW___KEY_UPPER___*` / vendor environment variables, immutable
  and validated ([Configuration](configuration.md)).
- **Retries** with full-jitter backoff and `Retry-After`, connect/request/total timeouts and
  cancellation in every language.
- **Typed errors** with one set of codes across languages ([Error handling](errors.md)).
- **Redaction everywhere**: credentials never appear in errors, logs, hooks or `toString`
  ([Redaction](redaction.md)).
<!-- @sdk-kit:if secrets -->
- **Secrets**: typed getters, bulk reads, `loadEnv`, watch and a TTL cache ([Secrets](secrets.md)).
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if logging -->
- **Logging**: batching log client, logger facade, redaction processor, framework adapters and
  log search ([Logging](logging.md)).
<!-- @sdk-kit:endif -->
<!-- @sdk-kit:if tracing -->
- **Tracing**: OpenTelemetry setup, span helpers, propagation, framework adapters and trace
  queries ([Tracing](tracing.md)).
<!-- @sdk-kit:endif -->
- **Service functions** for the __DISPLAY__ API ([Functions](functions.md)).

Start with [Install](install.md) and the [Quickstart](quickstart.md).

!!! note "Independent project"
    This SDK is made by [Grow Codes](https://grow.codes). __DISPLAY__ is a trademark of
    __VENDOR__. This project is not affiliated with or endorsed by __VENDOR__. See
    [License & disclaimer](license.md).
