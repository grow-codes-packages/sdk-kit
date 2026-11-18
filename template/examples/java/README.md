# Java examples

Install the package into your local Maven repository, point it at a running __DISPLAY__ and run an
example:

```bash
make -C ../../java pack            # builds and installs codes.grow.packages:__KEY__
export GROW___KEY_UPPER___URL=http://127.0.0.1:__PORT__
export GROW___KEY_UPPER___TOKEN=...   # when the service needs one
mvn -q compile exec:java                                                  # BasicExample
mvn -q compile exec:java -Dexec.mainClass=codes.grow.packages.__PKG__.examples.AsyncExample
```

Against the published package, set `-Dsdk.version=<version>` (or edit `pom.xml`) instead of
installing it locally.

| Class | Shows |
| - | - |
| `BasicExample` | blocking client: health, ping, server version, error handling |
| `AsyncExample` | `…Async` methods, combining futures, cancellation |
| `HooksAndLoggingExample` | request hooks, a logger, retries and timeouts |
<!-- @sdk-kit:if secrets -->
| `secrets.SecretsCacheExample` | cached secret reads, typed getters, `loadEnv`, `watch` (in-memory provider) |
<!-- @sdk-kit:endif -->
