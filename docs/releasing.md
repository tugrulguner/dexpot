# Releasing dexpot

Releases are maintainer operations. Feature pull requests add Towncrier fragments but do
not bump versions or create tags.

## Single version source

`project.version` in `pyproject.toml` is the only editable version value.
`dexpot.__version__` and both CLI version surfaces derive from installed package metadata.
Use uv so package metadata and `uv.lock` move together:

```bash
uv version --bump patch
# or: uv version <version>
```

Never edit a runtime version string or lockfile version by hand.

## Prepare the release pull request

1. Start from current `main` with no unrelated changes.
2. Update the version with `uv version`.
3. Preview fragments:

   ```bash
   make changelog-draft
   ```

4. Assemble the exact version section:

   ```bash
   make changelog
   ```

5. Inspect both staged and unstaged changes because Towncrier may stage generated changes:

   ```bash
   git status --short
   git diff --cached
   git diff
   ```

6. Run `make check` and `make build`.
7. Open a release pull request containing only version metadata, lockfile changes, generated
   changelog, and consumed fragments. Apply `skip-changelog` because the release pull
   request consumes its fragments.

## Tag and publication

After the release pull request is reviewed, green, and merged:

```bash
version="$(uv version --short)"
git tag "v${version}"
git push origin "v${version}"
```

`.github/workflows/release.yml` then:

1. reruns reusable CI at the tag;
2. verifies tag, `pyproject.toml`, and changelog version equality;
3. builds and inspects wheel and sdist from a clean cache boundary;
4. publishes to PyPI through the `pypi` environment and OIDC trusted publishing; and
5. creates a GitHub Release from the matching changelog section with the same artifacts.

Before the first tag, configure both sides of trusted publishing:

- a GitHub environment named `pypi` whose deployment policy admits release tags; and
- the exact PyPI trusted-publisher tuple for `tugrulguner/dexpot`,
  `.github/workflows/release.yml`, and environment `pypi`.

A workflow file declaring the environment does not create the PyPI publisher.

## Post-publication verification

In a fresh directory and environment, install the exact version from PyPI with caches
disabled. Verify import, both CLI version surfaces, skill installation, and a real HTTP
smoke. Compare PyPI artifact digests with the assets attached to the GitHub Release, check
the tag target, and confirm the release is neither draft nor unexpectedly prerelease.
