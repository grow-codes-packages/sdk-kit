# sdk-kit Docker harness

The Docker integration contract of every generated repository (SPEC §8) and the emulators some
services need.

| Path | What |
| - | - |
| `../template/common/docker/compose.yml` | harness compose file (sdk-kit-owned, synced): `test-<lang>` services, profile `<lang>` |
| `../template/common/docker/compose.service.yml` | placeholder for the service under test + `bootstrap` job (repo-owned, generated once) |
| `../template/common/docker/bootstrap/` | `bootstrap.sh` skeleton (repo-owned), `lib.sh` helpers (synced), README with the `/bootstrap/env` format |
| `../template/common/docker/harness/` | `compose-run.sh`, `wait-for-http.sh`, `wait-for-tcp.sh` (synced into `docker/harness/`) |
| `compose-run.sh`, `wait-for-*.sh` | symlinks to the template copies, for use inside sdk-kit |
| `moto/` | AWS emulator variant (`aws-secrets-manager`, `aws-cloudwatch-logs`) |
| `fakeintake/` | Datadog fakeintake variant (`datadog-logs`; backend for `datadog-apm`) + `fakeintake.py` query helper |
| `betterstack-stub/` | contract-verified Better Stack Logs intake + SQL API stub (`better-stack-logs`) |
| `../demo/` | the demo service (`sdk-kit new demo`) |
| `tests/` | harness tests; `render_repo.py` is the reference implementation of the docker/ layout rules |
| `GENERATOR_NOTES.md` | what the generator must do so the harness works |

## Compose layout of a generated repository

```
docker/compose.yml           include: compose.service.yml; test-typescript|rust|go|python|java
docker/compose.service.yml   service (healthcheck), bootstrap (one-shot), volume bootstrap
docker/bootstrap/            bootstrap.sh (+ lib.sh), mounted at /scripts
docker/harness/              compose-run.sh, wait-for-http.sh, wait-for-tcp.sh, mounted at /harness
docker/Dockerfile.<lang>     builds + packs the package, installs it into <lang>/integration, CMD = integration tests
```

Each `test-<lang>` container starts only after `service` is healthy **and** `bootstrap` exited 0,
mounts the `bootstrap` volume read-only at `/bootstrap`, and gets
`GROW_<KEY_UPPER>_URL=http://service:<port>`, `GROW_BOOTSTRAP_ENV=/bootstrap/env` and
`GROW_TEST_RUN_ID`. No service publishes host ports. Test images are tagged
`grow-sdk-<key>-test-<lang>:${GROW_TEST_IMAGE_TAG:-local}`.

## `compose-run.sh`

```sh
docker/harness/compose-run.sh [-f FILE]... [-p PREFIX | -P NAME] [-l none|auto|N|PATH] [-t SECONDS] [-n] <lang> [-- ARGS]
```

Unique project `<prefix>-<lang>-<random>`, `run --rm --build test-<lang>`, then always
`down -v --remove-orphans` (EXIT/INT/TERM trap; INT/TERM also stop the running suite at once), prints
`ps -a` + all service logs when the suite fails, keeps the suite's exit status (124 on `-t` timeout).
The test image is tagged with the project name and removed afterwards unless `GROW_TEST_IMAGE_TAG`
is set. `-l auto` takes the first free `sdk-docker-1..4.lock` (`SDK_DOCKER_LOCK_DIR`, default
`~/.cache/grow-sdk/locks`; on the shared dev server use `SDK_DOCKER_LOCK_DIR=~/grow/.artifcats/locks`),
otherwise waits for a random one. Never nest it inside an outer `flock` on the same file.

## Tests

```sh
make -C harness test          # pytest (demo 100 %, stub 98.5 %, fakeintake 99 %) + wait-for tests
make -C harness lint          # shellcheck + ruff
make -C harness test-docker   # end-to-end, under flock ~/grow/.artifcats/locks/sdk-docker-1.lock
```

`tests/test-compose-demo.sh` proves bootstrap env sharing (read-only), health gating (unhealthy
service and failing bootstrap keep the suite from starting), exit status propagation, log printing,
SIGTERM handling and complete cleanup (containers, volumes, networks, test image).
`tests/test-compose-emulators.sh` runs the moto, fakeintake and betterstack-stub variants as drop-in
`docker/compose.service.yml` files with probes that use `/bootstrap/env` like an SDK test would.
