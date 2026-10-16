# Experimental checked execution: draft status

This branch is a **draft**, not a release or a claim of performance qualification. It preserves the synchronous public API and checked-response guarantees while changing their execution mechanism. Do not merge the combined runtime defaults until the remaining performance gates are resolved.

## What is implemented

- FT-only straight-line scalar validation/public projection for eligible exact, default-free primitive Structs, with conservative incumbent fallback. Registration captures original member descriptors; missing slots and changed accessors fall back. Non-finite floats remain rejected, aliases remain public wire names, and returned subtypes/private protected values remain on the checked fallback.
- Per-serving-thread scalar function/global bindings derived from canonical registration code. This does not re-inspect application annotations per request or promise an atomic snapshot during concurrent class mutation.
- A bounded GIL idle-readiness owner. Active workers handle parsing, handlers and output; idle sockets do not permanently occupy handler workers. Pending work, connection count and stale deadline metadata remain bounded.
- A bounded hot-connection grace wait of at most 5 ms, immediate yielding to already queued peers, and an eight-request maximum turn. One absolute idle/head expiry survives worker-to-reactor handoff; grace does not restart the configured timeout.
- The absolute head deadline also survives reactor-to-ready-to-worker handoff and hot-grace reuse. Idle-read expiry remains separate, so receiving a fragment renews the idle-read wait without renewing the absolute head budget. New requests, including buffered pipeline requests, receive their own head budget.
- A parent-created listening socket shared by POSIX fork workers, child pool-readiness events, an accept gate, and explicit startup/drain resource ownership. FT remains single-process. This is not Windows multiprocessing support.
- Narrow Python parser byte fast paths retaining the reference error and framing behavior.

The small startup rollback fix was merged separately in [#115](https://github.com/tugrulguner/dexpot/pull/115). This draft is rebased onto that merged main commit; its remaining diff contains only the experimental execution work and supporting documentation/tests.

## Evidence and limits

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
