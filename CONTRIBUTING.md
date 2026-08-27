# Contributing to dexpot

Thanks for helping build dexpot as a synchronous API framework for GIL and free-threaded
CPython.

## Choose the right path

### Substantial contract work: open an issue first

Open a
[feature request](https://github.com/tugrulguner/dexpot/issues/new?template=feature.yml)
before substantial handler, routing, parser, scheduler, protocol, or execution-model work.
Start with the user problem and wait for agreement on the public contract before implementing
it.

### Small direct changes

Focused documentation, regression tests, clearly scoped bug fixes, and repository maintenance
may go directly to a pull request when they do not introduce a new public contract. Explain
why a direct pull request is appropriate in the template.

### Questions and early ideas

Use [Q&A](https://github.com/tugrulguner/dexpot/discussions/categories/q-a) for usage help and
[Ideas](https://github.com/tugrulguner/dexpot/discussions/categories/ideas) for an idea that is
not yet a scoped proposal.

### Claimed community work

Search open issues, every issue comment, and open pull requests before starting. For a `good
first issue` or `help wanted` issue, comment and wait for confirmation before implementation
so contributors do not duplicate work. Use the
[bug report form](https://github.com/tugrulguner/dexpot/issues/new?template=bug.yml) for
reproducible failures.

## Development setup

```bash
git clone https://github.com/tugrulguner/dexpot.git
cd dexpot
uv sync --all-extras
uv run pre-commit install
make check
```

Use `make format` before committing.

## What a change must preserve

- Plain synchronous handlers; no coroutine bridge in the request path.
- Route and argument errors fail during registration when they can be known then.
- A worker owns a keep-alive connection until close.
- GIL admission remains bounded and returns 503 instead of accumulating unlimited work.
- Free-threaded and GIL behavior are tested deliberately rather than assumed equivalent.
- Public performance claims come from reproducible, correctness-matched benchmarks.

The rules above come from the route-binding, keep-alive, signal, and multiprocess bugs
already exercised by the end-to-end suite. Treat them as architecture contracts rather
than style preferences.

## Tests

Run the complete gate:

```bash
make check
```

The gate includes lint, formatting, type checking, real HTTP tests, and coverage. Useful
narrower commands are:

```bash
uv run pytest tests/test_e2e.py -v
uv run pytest tests/test_multiprocess.py -v
uv run pytest tests/test_add_skills.py tests/test_skills_content.py -v
```

Record exact commands, environment details, and results so a reviewer can reproduce the
evidence rather than infer it from a green summary.

A behavior change needs an end-to-end test against the real socket server. A unit test of a
private helper is not enough by itself. Multiprocess, signal, restart, and drain behavior
must run in a subprocess because Python only permits signal handlers in the main thread.

## Pull requests

1. Branch from the latest `main`.
2. Link the agreed issue with `Closes #<issue-number>` when one exists.
3. Keep the change focused on one concern. Open a draft pull request when early feedback is
   useful; a draft is not required for every change.
4. Add or update real-user tests and executable examples when behavior changes.
5. Update README, roadmap, agent skill, and contributor guidance in the same change when
   their contract changes.
6. Add a changelog fragment for a user-facing change.
7. Run `make check`, `make build`, and the workflow checks in
   [`docs/reviewing.md`](docs/reviewing.md).
8. Open the pull request with the current behavior, the change, and verification evidence.

## Changelog fragments

User-facing changes require one Towncrier fragment. If the change has an issue, use that
issue number:

```text
changelog.d/<issue-number>.<type>.md
```

For a small change without an issue, let Towncrier create a unique orphan fragment:

```bash
uv run towncrier create +.changed.md
```

Types are `added`, `changed`, `deprecated`, `removed`, and `fixed`. Write one sentence about
what changed for a user, not how the patch was implemented. Replace `changed` in the command
with the appropriate type. Run `make changelog-draft` to preview it. Do not edit
`CHANGELOG.md` directly; Towncrier assembles it during release preparation. For maintenance
with no user-visible effect, a maintainer may apply the `skip-changelog` label.

## Releasing

Maintainers follow [`docs/releasing.md`](docs/releasing.md). Do not bump the version or tag a
feature pull request. `pyproject.toml` is the one editable version source; `uv version`
updates it and the lockfile together.

## Reporting issues

Search existing issues first, then use the
[bug report form](https://github.com/tugrulguner/dexpot/issues/new?template=bug.yml). A useful
report includes:

- Python version and whether `sys._is_gil_enabled()` is true or false;
- operating system;
- a minimal runnable application;
- the exact request and observed response;
- concurrency settings such as `DEXPOT_POOL`, `DEXPOT_MAX_QUEUE`, and `DEXPOT_WORKERS`;
- whether the failure reproduces with a single connection and a single process.

Remove secrets, credentials, tokens, and private connection strings from reproductions and
logs before posting them publicly.

For substantial API or scheduler changes, open an issue and align on the contract before
implementation.
