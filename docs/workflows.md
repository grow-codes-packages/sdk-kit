# Workflows reference

Generated repositories keep their workflows tiny: `ci.yml`, `release.yml` and `docs.yml` call the
reusable workflows of sdk-kit (`uses: grow-codes-packages/sdk-kit/.github/workflows/<file>@main`,
to be pinned to `@v0` after the first sdk-kit release). Third-party actions are pinned by full
commit SHA with the version in a comment; every job declares least-privilege `permissions`.

## Language pipelines

Each runs the language Makefile contract `deps lint build test coverage license pack` in the
language folder.

| Workflow | Matrix (primary in bold) | Primary job extras |
| - | - | - |
| `lang-typescript.yml` | Node 22, **24** | artifacts `coverage-typescript`, `dist-typescript` |
| `lang-rust.yml` | **stable**, MSRV 1.88 (build + test) | cargo-llvm-cov, cargo-deny; artifacts `coverage-rust`, `dist-rust` |
| `lang-go.yml` | **1.26**, 1.27 | golangci-lint, go-licenses; artifact `coverage-go` |
| `lang-python.yml` | 3.10, **3.13**, 3.14 | artifacts `coverage-python`, `dist-python` |
| `lang-java.yml` | Temurin 17, **21**, 25 | artifacts `coverage-java`, `dist-java` |

Non-primary entries run `deps build test` (Go: also lint and coverage).

| Input | Default | Meaning |
| - | - | - |
| `working-directory` | the language folder | folder with the package and its Makefile |
| `runs-on` | `ubuntu-24.04` | runner label |
| `source-artifact` | empty | artifact holding `source.tar` (a rendered repo) instead of a checkout — used by sdk-kit CI for the demo |
| `upload-artifacts` | `true` | upload coverage and package artifacts |

`coverage/summary.json` has the shape
`{"lines": {"covered", "total", "pct"}, "branches": {…} | null}`.

## `docker-integration.yml`

Runs `make test-docker LANGS=<lang>` from the repository root (the real service, the bootstrap
container and the `test-<lang>` consumer image). On failure it uploads `compose-logs-<lang>`:
the root Makefile writes `docker compose logs` into `$COMPOSE_LOGS_DIR` before its `down -v`, and
the workflow adds the logs of any container still present.

| Input | Default |
| - | - |
| `lang` | required: `typescript`, `rust`, `go`, `python` or `java` |
| `working-directory` | `.` |
| `timeout-minutes` | 45 |
| `runs-on`, `source-artifact` | as above |

## `sdk-kit-check.yml`

Checks out sdk-kit at `sdk-kit-ref` (default `main`) outside the repository tree, runs
`sdk-kit check --dest .` and reports `sdk-kit sync --dry-run` drift as a notice.

## `docs.yml`

1. Builds the MkDocs Material site from the root `mkdocs.yml` (tools pinned in
   `docs/requirements.txt`; Python API via mkdocstrings).
2. Builds TypeDoc (`api/typescript/`), rustdoc (`api/rust/`) and Javadoc (`api/java/`) with
   `make -C <lang> docs` and copies them into the site. Go links to pkg.go.dev.
3. Writes shields.io endpoint badges `badges/coverage-<lang>.json` from the `coverage-<lang>`
   artifacts of the run — or of the latest successful `coverage-workflow` run on the default
   branch when the run has none. Missing data shows `unknown`.
4. With `deploy: true`, deploys with `actions/deploy-pages`. If GitHub Pages is not set to
   "GitHub Actions" yet, the deploy job ends green with a notice.

| Input | Default |
| - | - |
| `deploy` | `false` |
| `api-reference` | `true` |
| `coverage-workflow` | `ci.yml` |

Caller permissions: `contents: read`, `actions: read`, `pages: write`, `id-token: write`.

## `release-packages.yml`

release-please (manifest mode; packages `typescript`, `rust`, `go`, `python`, `java`) keeps one
release PR. When it is merged, each released package is published:

| Package | Publish | Enabled when |
| - | - | - |
| npm | `npm publish --provenance --access public` (trusted publishing via OIDC) | input `npm-trusted-publishing` or secret `NPM_TOKEN` |
| crates.io | `rust-lang/crates-io-auth-action` + `cargo publish` | input `crates-trusted-publishing` or secret `CARGO_REGISTRY_TOKEN` |
| Go | ensures the `go/vX.Y.Z` tag, then `GOPROXY=https://proxy.golang.org go list -m <module>@vX.Y.Z` | always (no credentials) |
| Maven Central | `mvn -P release deploy` (central-publishing-maven-plugin + maven-gpg-plugin in the `release` profile of `java/pom.xml`) | secrets `MAVEN_CENTRAL_USERNAME`, `MAVEN_CENTRAL_PASSWORD`, `MAVEN_GPG_PRIVATE_KEY` (+ `MAVEN_GPG_PASSPHRASE`) |
| PyPI | reusable job `python-build` uploads `python-dist`; the **caller's** `pypi` job uploads it with `pypa/gh-action-pypi-publish` | repository variable `PYPI_TRUSTED_PUBLISHING=true` |

A publish job whose credentials or trust are missing ends green with a notice, so CI stays green
until the registries are set up. PyPI trusted publishing does not accept reusable workflows,
which is why the PyPI upload lives in each repository's own `release.yml` (job `pypi`, environment
`pypi`, `id-token: write`).

Outputs: `releases-created`, `paths-released`, `<lang>-version`, `python-release-created`.

### Registry setup checklist (per repository)

| Registry | Trusted publisher settings | Then |
| - | - | - |
| npm | repository `grow-codes-packages/<key>`, workflow `release.yml` | variable `NPM_TRUSTED_PUBLISHING=true` |
| crates.io | repository `grow-codes-packages/<key>`, workflow `release.yml` | variable `CRATES_TRUSTED_PUBLISHING=true` |
| PyPI | repository `grow-codes-packages/<key>`, workflow `release.yml`, environment `pypi` | variable `PYPI_TRUSTED_PUBLISHING=true` |
| Maven Central | namespace `codes.grow.packages` verified, user token, GPG key published | the four `MAVEN_*` secrets |
| GitHub Pages | Settings → Pages → Source: GitHub Actions | — |

The variables can be set once at organization level.

## sdk-kit's own workflows

| Workflow | Jobs |
| - | - |
| `ci.yml` | generator `make lint test check-all` (Python 3.10, 3.13); render `demo`; the five language pipelines, Docker integration per language, `sdk-kit check` and the docs build on the rendered demo (via the local reusable workflows); actionlint; sdk-kit's own docs (deployed from `main`) |
| `release.yml` | release-please (tags `vX.Y.Z`, first `v0.1.0`) and the moving major tag `v0` |
