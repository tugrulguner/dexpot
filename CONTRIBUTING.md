# Contributing to dexpot

Thanks for helping build dexpot as a synchronous API framework for GIL and free-threaded
CPython.

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

A behavior change needs an end-to-end test against the real socket server. A unit test of a
private helper is not enough by itself. Multiprocess, signal, restart, and drain behavior
must run in a subprocess because Python only permits signal handlers in the main thread.

## Pull requests

1. Branch from the latest `main`.
2. Keep the change focused on one concern.
3. Add or update real-user tests and executable examples when behavior changes.
4. Update README, roadmap, agent skill, and contributor guidance in the same change when
   their contract changes.
5. Add a changelog fragment for a user-facing change.
6. Run `make check`, `make build`, and the workflow checks in
   [`docs/reviewing.md`](docs/reviewing.md).
7. Open a pull request with the current behavior, the change, and verification evidence.

## Changelog fragments

User-facing changes require one file named for the pull request:

```text
changelog.d/<pr-number>.<type>.md
```

Types are `added`, `changed`, `deprecated`, `removed`, and `fixed`. Write one sentence about
what changed for a user. Do not edit `CHANGELOG.md` directly; Towncrier assembles it during
release preparation. For maintenance with no user-visible effect, a maintainer may apply
the `skip-changelog` label.

## Releasing

Maintainers follow [`docs/releasing.md`](docs/releasing.md). Do not bump the version or tag a
feature pull request. `pyproject.toml` is the one editable version source; `uv version`
updates it and the lockfile together.

## Reporting issues

Search existing issues first. A useful bug report includes:

- Python version and whether `sys._is_gil_enabled()` is true or false;
- operating system;
- a minimal runnable application;
- the exact request and observed response;
- concurrency settings such as `DEXPOT_POOL`, `DEXPOT_MAX_QUEUE`, and `DEXPOT_WORKERS`;
- whether the failure reproduces with a single connection and a single process.

For substantial API or scheduler changes, open an issue and align on the contract before
implementation.
