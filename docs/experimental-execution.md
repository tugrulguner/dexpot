# Experimental checked execution: draft status

This branch is a **draft**, not a release or a claim of performance qualification. It preserves the synchronous public API and checked-response guarantees while changing their execution mechanism. Do not merge the combined runtime defaults until the remaining performance gates are resolved.

## What is implemented

- FT-only straight-line scalar validation/public projection for eligible exact, default-free primitive Structs, with conservative incumbent fallback. Registration captures original member descriptors; missing slots and changed accessors fall back. Non-finite floats remain rejected, aliases remain public wire names, and returned subtypes/private protected values remain on the checked fallback.
- Per-serving-thread scalar function/global bindings derived from canonical registration code. This does not re-inspect application annotations per request or promise an atomic snapshot during concurrent class mutation.
- A bounded GIL idle-readiness owner. Active workers handle parsing, handlers and output; idle sockets do not permanently occupy handler workers. Pending work, connection count and stale deadline metadata remain bounded.
- A bounded hot-connection grace wait of at most 5 ms, immediate yielding to already queued peers, and an eight-request maximum turn. One absolute idle/head expiry survives worker-to-reactor handoff; grace does not restart the configured timeout.
- The absolute head deadline also survives reactor-to-ready-to-worker handoff and hot-grace reuse. Idle-read expiry remains separate, so receiving a fragment renews the idle-read wait without renewing the absolute head budget. New requests, including buffered pipeline requests, receive their own head budget.
- A parent-created listening socket shared by POSIX fork workers, child pool-readiness events, an accept gate, and explicit startup/drain resource ownership. GIL-disabled execution remains single-process. This is not Windows multiprocessing support.
- Narrow Python parser byte fast paths retaining the reference error and framing behavior.

The small startup rollback fix was merged separately in [#115](https://github.com/tugrulguner/dexpot/pull/115). This draft is rebased onto that merged main commit; its remaining diff contains only the experimental execution work and supporting documentation/tests.

## Runtime-identity hardening and targeted rechecks

The verification gap is addressed on this draft; performance promotion is **not** cleared.
A free-threaded build and a running GIL-disabled process are recorded separately.

- `scripts/verify_runtime_mode.py` checks the actual serving process after application
  imports, startup, representative valid/invalid typed HTTP routes, raw output and a lazy
  import. It rejects GIL launch overrides; ordinary native-wheel integration no longer
  forces `-X gil=0`. On POSIX FT CI, a compiled extension with no free-threading support
  declaration must enable the GIL and be detected at both startup and lazy import.
  A separate unforced case verifies the legitimate free-threaded-build/GIL-enabled mode.
- Scheduling is bound at `serve()` after application loading. Startup labels distinguish
  standard Python/GIL enabled, free-threaded Python/GIL disabled and free-threaded
  Python/GIL enabled. A later change is warned about at connection admission or accept
  timeouts; the running scheduler is not silently migrated. There is no added GIL query
  during request dispatch and no new production configuration surface.
- The benchmark fixture emits startup and post-drain identities from every serving PID,
  including dependency versions and launch overrides. Its validator rejects missing,
  duplicate, mismatched or forced-mode evidence. A fixture-only shared lock serializes
  records across workers without assuming Linux's pipe atomic-write limit on macOS.
  These records prove worker presence/state, not balanced request participation.
- These checks qualify Dexpot's tested dependencies and integrations. Neither retained
  disabled-GIL state nor a compatibility tracker proves arbitrary application code is
  safe under concurrent requests.

Four prior losing workloads were rechecked with the exact installed runtime wheel
`c6dbfe14d0ab10856acfc33dcbb43666c0fb5a0d25ce72cbdc451f99b88ec2d2`,
frozen runtime/fixture commit `505bcb0bf48dd664d903dd667873e8963093e715`.
The later guard-only Windows PID correction does not change runtime or fixture bytes.
Every Python runtime member was checked against the wheel, frozen source and delivered
checkout. Full definitions, fingerprints and observed identities are in
[`runtime-identity-rechecks.json`](../benchmarks/checked_execution/runtime-identity-rechecks.json).

| Rechecked workload | Correct replies/s | p99 | Observed mode |
| --- | --- | --- | --- |
| Ubuntu GIL, mixed fixed load | 9,998.37 | 7.507 ms scheduled | GIL enabled, all four worker PIDs |
| Ubuntu FT, mixed fixed load | 9,998.47 | 5.027 ms scheduled | GIL disabled |
| Ubuntu FT, mixed capacity | 16,496.08 | 9.642 ms closed-loop | GIL disabled |
| macOS GIL, mixed fixed load | 9,982.53 | **48.351 ms scheduled** | GIL enabled, all four worker PIDs |

All four records passed runtime-identity validation: 20 startup/post-workload snapshots
from 10 distinct serving PIDs, 2,788,935 correct replies, zero body mismatches and zero
reported transport errors. No automatic GIL fallback was observed in the new FT rechecks.
This does **not** retrospectively establish lifetime GIL state in the older campaign,
which had startup-only checks. Candidate-only rechecks establish no capacity ratio or
full qualification. The macOS GIL scheduled-tail failure remains; original gates and
all adverse records are retained.

Local `make check build` passed (557 tests, 21 skips); the full FT source suite passed
(553 tests, 25 skips). Clean installed-wheel suites at the initial hardening snapshot
passed on macOS FT and Ubuntu GIL. Ubuntu FT first failed the previously observed
4-versus-3 process-thread-count assertion, then passed one unchanged full rerun; both
logs remain and no cause or fix is claimed. Windows native CI exposed a separate guard
assumption: a venv redirector's launcher PID can differ from the Python server PID.
The guard now anchors HTTP snapshots to the actual process's private per-launch import
record and retains both PIDs; regressions cover legitimate redirection and a genuinely
mismatched server. This does not relax the GIL-state or same-server requirements.

## Latest complete performance qualification: failed

The completed 32-trial campaign measured runtime commit
`4225a3babd8536c0ffc9faee371f10628d9e9853` against the prior draft head
`4b97265832c8df72ef5fec017904765f09c82203`, not against released Dexpot.
The runtime change removes redundant exact-socket timeout updates and unnecessary
GIL completion broadcasts. It does **not** include the ctypes/libc socket experiment;
Python still owns socket I/O and the native boundary remains parser-only.

The frozen installed wheel has SHA-256
`67641d759d2ba7cab816970509331296fcfb3cd582ecb542d233989d76c59e65`.
Every Python runtime member was checked against the wheel, sdist, frozen source and
published runtime checkout. Documentation-only follow-ups do not change those runtime
bytes. Full cell definitions, source/client/harness fingerprints, interpreter/import
identity, metrics, sampled resources and failure details are retained in
[`qualification.json`](../benchmarks/checked_execution/qualification.json).

The declared gates were unchanged: 10,000 offered requests/s within ±5%, scheduled
p99 at most 20 ms, exact responses and zero reported errors, candidate/control capacity
goodput ratio at least 0.95, and the recorded CPU/RSS/thread/fd budgets. Each cell was
configured for 60 seconds; fixed-load comparisons used ABBA order. No failed timed cell was
replaced or selectively retried.

| Failed candidate cell | Recorded outcome | Acceptance |
| --- | --- | --- |
| Ubuntu GIL, second fixed-load trial | 9,270.27 correct replies/s; scheduled p99 8,683.519 ms | Rate and scheduled-tail failure |
| macOS GIL, first fixed-load trial | 9,996.25 correct replies/s; scheduled p99 33.471 ms | Scheduled-tail failure |
| Ubuntu FT, first fixed-load trial | Client exited -6 in HDR `counts_index`; no final metrics | Invalid trial, not a latency pass |
| Ubuntu FT, mixed capacity | 23,251.04/s versus control 80,241.17/s; ratio 0.2898 | Capacity failure |

All 32 trial records were collected; 31 have complete, exact-response/zero-reported-error
results. Those 31 reported 32,439,698 correct replies and zero body mismatches. The
crashed client's reply count and error totals are unknown, not zero. Seven of eight
capacity pairs passed their frozen gate. Candidate sampled resource checks passed,
but neither the fixed-load nor overall capacity gate passed. One Ubuntu GIL control
also missed offered rate, so do not infer matched-load relative latency from that pair.

Evidence is macOS and Ubuntu ARM64 Docker loopback on a shared host, not bare-metal
Linux, separate-host load generation, a soak or framework leadership. The observed
failure is sufficient to withhold promotion; the measurements do not establish every
underlying cause.

### Follow-up diagnostics, not replacement qualification

- Request-count instrumentation reproduced nonuniform GIL process distribution. One
  candidate trial had per-worker connection counts 5/0/6/5 and scheduled p99 303.871 ms;
  another had 5/1/5/5 and 4.915 ms. An idle process and concentrated work are observed,
  not proof that distribution alone explains every failure.
- Removing periodic idle-worker waits did not clear the tail screen and was not promoted.
- Four FT source-only capacity ablations showed substantial run-to-run variation; they
  do not establish a causal explanation for the installed campaign's capacity loss.
- The original fixed-rate client crash was reproduced with line-buffered stdout. A
  separately rebuilt, stack-instrumented diagnostic client completed two trials without
  that crash. This is not a fix for the original client or a replacement for its failed
  qualification record; its underlying cause remains unresolved.
- Earlier ctypes and other adverse campaigns remain retained outside this campaign.
  Neither a favorable diagnostic nor green CI clears the failed performance gates.

### Correctness and review of the runtime repair

Three new regression cases failed before the repair and passed afterward; the shutdown
broadcast control also passes. `make check build` passed: GIL 526 passed/19 skipped,
lint/format/Pyright, wheel and sdist. Clean installed-wheel suites passed: macOS FT
521/24, Ubuntu GIL 525/20 and Ubuntu FT 517/28. The first macOS FT invocation omitted
the environment's bin directory from PATH and failed console-script discovery; the
unchanged artifact passed after correcting PATH, and the failed invocation is retained.

Exact-runtime-head CI passed. Independent static review found no new correctness
blockers in the narrow repair, while explicitly retaining the overall changes-required
verdict for performance promotion. This is not whole-draft merge approval.

## Historical evidence and limits

The recorded workload is in `benchmarks/checked_execution/`. All measurements below use checked native response paths and exact response-body validation. The older competitor comparison has different invalid-output guarantees: native FastAPI does not reject a protected Request hidden in discarded private fields. It is not an equal-contract universal ranking.

### Latest deadline-corrected source

ABBA predecessor/candidate/candidate/predecessor, GIL 4 processes, pool 22, 16 persistent connections, 4 client threads, mixed traffic, 10,000 offered requests/s, 25-second genuine wrk2 trials:

| Platform | Predecessor scheduled p99 | Candidate scheduled p99 | Outcome |
| --- | --- | --- | --- |
| macOS | 6.331 ms, 4.363 ms | 3.197 ms, 3.407 ms | All four achieved rate; candidate clears the predeclared 20 ms budget |
| Ubuntu ARM64 Docker | 649.727 ms, 9,674.751 ms | 7,172.095 ms, 7,282.687 ms | Candidate achieved only 8,824/s and 8,850/s; **not qualified**; one control also missed rate |

The control is the reviewed experimental predecessor, **not released Dexpot**. Completed responses validated with zero recorded response/transport errors: macOS 999,667 replies; Ubuntu 896,638 replies. Invalid offered-rate records remain in the evidence; their percentiles do not establish a valid matched-rate comparison.

Sampled macOS process-tree lifetime CPU was 112.19/128.41 s for the predecessor and 37.57/37.88 s for the candidate. This includes startup/teardown, not an isolated per-request CPU measurement. Peak sampled tree RSS was approximately 100–103 MiB. These are short paired results on one host, not sustained production SLO/resource qualification.

The exact measured Python-source hashes and compact trial metrics are in `benchmarks/checked_execution/evidence.json`. The source wheel used for these trials had SHA-256 `63762ee3f25dbc001bb0335e6e8085922a0078ab95c6648254dd5d7615d32d59`; PR documentation/test-compatibility additions can change the rebuilt archive hash. Verify source fingerprints instead of assuming archive identity.

The later review repair for reactor-to-worker head-deadline propagation changes runtime source beyond those recorded fingerprints. The historical trials remain evidence for their measured source only; they do not qualify this repaired artifact. Fresh performance qualification remains required.

### Earlier source generations are separate evidence

A pre-startup-review installed-wheel campaign measured mixed capacity of 25,320/s GIL and 82,283/s FT versus release 18,004/s and 31,243/s, and tested FastAPI/Granian 13,976/s and 11,218/s. Those are **not measurements of this exact PR artifact**. Saturated tails worsened; later FT matched-load trials reached 36.639/95.487 ms against a 20 ms budget. No later GIL-only repair clears those FT failures.

Request-correlated diagnostics found low-CPU elapsed stalls and delayed-start versus actual-send latency differences. An OS scheduling-policy experiment worsened p99 and was rejected. No scheduler policy adapter, diagnostic sampler or weakened latency metric is included here. A low actual-send percentile never substitutes for a failed scheduled percentile.

## Correctness verification before publication

- Deadline-corrected source: macOS GIL 510 passed/19 skipped; FT 511/18. Ubuntu installed-wheel GIL 509/20; FT 507/22.
- Independent public HTTP lifecycle/fairness suite: 5 passed on each OS.
- Parser differential checks cover all 256 byte values; response regression coverage includes aliases, constraints, defaults, subtype/private Request, changed descriptors, nonfinite values, and unset slots with custom accessors.
- Independent CLI review found two startup-allocation leaks and the grace/idle double-deadline defect. Each was reproduced, corrected and re-reviewed; the final bounded-hot-lease review reported no remaining correctness blockers within its scope. This is not an exact-PR-head review or performance approval.
- The publication branch additionally retains #115's four real-socket partial-startup tests and uses safe GIL-query fallbacks in FT-only tests for Python 3.12. Fresh local and GitHub CI results must be evaluated for the published head.

## Merge blockers / remaining work

- [ ] Resolve Ubuntu offered-rate failure or demonstrate its measurement limitation with reproducible evidence. Persistent-HTTP PID probing already observed all four workers; do not simply assume listener imbalance.
- [ ] Clear the FT scheduled-latency gate; the GIL grace change does not modify the FT path.
- [ ] Repeat relevant capacity, mixed/large response, tail and resource checks on the final installed artifact; retain every adverse cell.
- [ ] Pass current-head CI (including supported interpreter modes, native parser parity/artifacts and website checks).
- [ ] Obtain and verify exact-published-head review. Do not reuse predecessor approval without checking the diff and fingerprints.

No release version, dependency lockfile, public configuration knob or global “fastest framework” promise is introduced.
