# Contributing to sdk-kit

Thank you for helping! sdk-kit generates every Grow Codes service SDK repository, so a change here
reaches 17 repositories in five languages. Please read [AGENTS.md](AGENTS.md) first and follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately, see
[SECURITY.md](SECURITY.md).

## Before you open a pull request

- `make lint test` passes (coverage gate: ≥ 90 % lines and ≥ 90 % branches).
- For template changes: render the affected services (`bin/sdk-kit new <key> --dest build/<key>
  --force` or `make check-all`) and run `make lint coverage` inside the rendered language folders,
  for all categories together and for each single category.
- API changes follow `spec/SPEC.md` and land in all five languages together.
- The generator stays standard-library only at runtime and supports Python 3.10+.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat(template/go): …`,
`fix(generator): …`, `docs: …`).

## Licence

By contributing you agree that your contribution is licensed under the
[Apache License, Version 2.0](LICENSE).
