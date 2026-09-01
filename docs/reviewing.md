# Reviewing a change to dexpot

Use this for local changes and pull requests. The architecture contracts in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) are the project-specific criteria.

## 1. Gather the exact change

For a pull request:

```bash
gh pr view <number> --json title,body,state,baseRefName,baseRefOid,headRefName,headRefOid,commits,files,statusCheckRollup
gh pr diff <number>
gh api repos/tugrulguner/dexpot/pulls/<number>/reviews
gh api repos/tugrulguner/dexpot/pulls/<number>/comments
```

### Pin the exact head

Record the reviewed head SHA and fetch it into an immutable review ref:

```bash
HEAD_SHA=$(gh pr view <number> --json headRefOid --jq .headRefOid)
git fetch origin "pull/<number>/head:refs/remotes/review/<number>"
test "$(git rev-parse refs/remotes/review/<number>)" = "$HEAD_SHA"
```

Run the review from that commit. Before publishing findings or merging, query GitHub again
and confirm the live head still equals the reviewed head SHA. Also compare the branch against
current main; a green result against an obsolete base is not integration evidence.

For local work, inspect `git status --short`, the unstaged diff, and the staged diff.
Untracked files are part of the change.

## 2. Understand the current architecture

Read the touched files and their callers before judging a diff. For route changes, trace
declaration and freeze separately from request execution:

```text
declaration: registration -> EndpointPlan
freeze: EndpointPlan declarations -> RouterPlan.compile(...) -> ApplicationPlan(router=RouterPlan)
request: ApplicationPlan.router -> RouterPlan.match(...) -> EndpointPlan -> decode/bind -> handler
                                                                              -> encode/send

connection: accept -> admission -> connection owner -> drain
```

A diff-only review misses contracts split between registration, immutable application freeze,
scheduling, and shutdown.

## 3. Apply the dexpot criteria

Prioritize:

- registration-time correctness for routes and handler signatures;
- real HTTP behavior, including malformed input and keep-alive;
- bounded GIL admission and truthful 503 behavior;
- free-threaded versus GIL branch differences;
- worker listener ownership, restart, and atomic teardown;
- signal handling in the main thread;
- public failure leakage; and
- documentation claims that exceed implementation.

## 4. Run the checks that matter

Always run:

```bash
make check
make build
git diff --check
```

Then choose targeted evidence:

| Changed area | Additional verification |
|---|---|
| route compilation or binding | registration/freeze atomicity + annotation resolution + real HTTP path/body/keyword-only cases |
| parser or response path | malformed socket input + keep-alive + disconnect cases |
| pool or admission | saturation test proving bounded queue and 503 responses |
| multiprocessing | subprocess liveness, worker crash/restart, SIGTERM drain, listener closure |
| README or public API | docs/skill tests, Python block compilation, built-wheel smoke |
| workflows | YAML parse, Actionlint, Zizmor, and clean locked command reproduction |
| performance | `wrk` with equivalent successful responses and reported error/latency distributions |

Do not test signals by running `serve()` in a thread. Do not use a Python HTTP client as a
headline load generator.

For framework scheduler changes, deliberately exercise the GIL and free-threaded branches and
record the Python version plus `getattr(sys, "_is_gil_enabled", lambda: True)()`. For signal
handling, worker restart, or draining changes, launch a subprocess and verify process exit and
listener closure.

## 5. Verify each finding

Execute a reproducer when possible. Before claiming a negative check proves safety, make
sure the check would fail if the bug were present. A green suite cannot prove tests were not
deleted; compare test inventories after conflict resolution.

Classify findings:

- **High** — correctness, security, unbounded work, broken shutdown, or false public claims;
  blocks merge.
- **Medium** — important design inconsistency or missing acceptance coverage; should fix.
- **Low** — optional improvement.

Few verified findings are better than many plausible ones. Do not review formatter output
or request comments on working code.

## 6. Review the built artifact

Build outside assumptions made by an editable checkout:

```bash
uv build
```

Inspect that one wheel and one sdist exist, the wheel contains `dexpot/__init__.py` and the
packaged skill template, and the sdist contains source, README, roadmap, and contributor
documentation. Install the wheel in a fresh environment outside the repository and verify:

- `dexpot --version`;
- `dexpot add skills --agent claude`;
- import of `Dex`; and
- a real GET and typed POST through a served installed-package application.

## 7. Report against the exact head

Post findings against `headRefOid`, then read the review and inline comments back from
GitHub. Before a clean verdict, re-fetch the head, confirm checks are green at that SHA, and
ensure the PR description still matches its final implementation.
