# TypeScript integration tests

A consumer project: it installs the packed `@grow-codes/__KEY__` tarball (never the source tree)
and runs the integration and conformance tests with `node --test` against a real **DISPLAY**.

```sh
cd typescript && make pack            # writes dist/grow-codes-__KEY__-<version>.tgz
cd integration && npm run install-package
GROW___KEY_UPPER___URL=http://127.0.0.1:<port> GROW___KEY_UPPER___TOKEN=... npm test
```

In CI and locally with Docker this runs inside `docker/Dockerfile.typescript`
(`make test-docker LANGS=typescript` from the repository root), which reads `/bootstrap/env`.
