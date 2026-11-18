# Releasing sdk-kit

sdk-kit uses [release-please](https://github.com/googleapis/release-please) with Conventional
Commits on `main` (`feat:`, `fix:`, `feat!:`):

1. Every push to `main` updates the release PR (version bump in `sdk_kit/__init__.py`,
   `CHANGELOG.md`).
2. Merging it tags `vX.Y.Z` and creates the GitHub release. The first release is `v0.1.0`
   (config: `.github/release-please-config.json`, manifest `.github/.release-please-manifest.json`).
3. The `major-tag` job moves `v0` (the major) to the new release.

Generated repositories call the reusable workflows and check out sdk-kit by ref. Until `v0.1.0`
exists they use `@main`; afterwards they pin `@v0` (minor and patch releases arrive automatically,
a new major is an explicit change).

To let the release PR trigger CI, add a `RELEASE_PLEASE_TOKEN` secret (a fine-grained token or
GitHub App token with contents and pull-requests write); without it the default `GITHUB_TOKEN` is
used and CI on the release PR must be started by hand.
