# GIL nested response preparation: installed-wheel experiment

## Status and scope
Implementation included in v0.8.0; the measurements below remain historical pre-release evidence, not a v0.7.1-to-v0.8.0 comparison. Measured source `45df5f1dd2c634874316c2fe977708dd8f5cb092` against public v0.7.1 whose runtime sources equal base `ed552cf80d2940df2644d9840401cf9d823c0f44`. File SHA256 in the companion JSON pins the measured legacy compiler; later report-only commits do not change it. Both wheel versions are 0.7.1; their artifact/source hashes distinguish the private candidate from PyPI.

This is a same-host macOS diagnostic with native wrk adjusted closed-loop percentiles, not a general release-to-release, Linux, external-framework, fixed-load SLO or production qualification claim. Unrelated host load was not controlled. FT measurements do not establish an improvement: its serving strategy is unchanged.

## Mechanism and preserved boundaries
The GIL legacy compiler captures schema metadata it already inspected. After existing registration/default validation, supported required nested Struct contracts select the existing direct compiler once, with the complete canonical graph as fallback. Flat/scalar/default/custom-access/unsupported contracts retain the exact canonical callable, without another request wrapper. Python 3.12's missing GIL query is handled; no GIL query or TLS binding is added to requests. The existing direct compiler, all 36 guards, slot captures, MRO checks and FT strategy remain unchanged. No validation, conversion, projection, default/factory, Request-leak or finite-value checks are removed.

The previous six-guard deduplication candidate remains rejected and is not included. Profiling identified repeated ordinary-GIL scalar-validator calls; the isolated strategy probe is motivation, not the HTTP result below.

## Correctness and artifact checks
- Strict RED/GREEN selection regression, plus parent-reproduced unsupported root Required wrapper TypeError/KeyError regression repaired before measurement.
- 635 standard tests / 26 skips; 649 real unforced FT tests / 12 skips; 30 focused tests on actual Python 3.12. Full canonical formatting/lint/typecheck/coverage passed.
- 18 byte/outcome EndpointPlan cases independently matched the installed incumbent in each runtime: malformed fields, int-to-float, enum, private projection, hidden Request, non-finite, deleted slots, descriptor mutation after registration, defaults/factories and root lists.
- Clean wheel/sdist build. Installed wheel CLI and all four real HTTP examples passed on both modes. Real HTTP activation showed the original 36 direct guards on GIL nested output and unchanged FT behavior. Diagnostics were absent from timed servers.

## Frozen primary screen
Two five-second repeats, flat/nested/mixed, GIL/FT: 12 cells per wheel, all 12 pair gates passed. Existing minimum goodput ratio 0.90, maximum adjusted-p99 ratio 1.25 and resource budgets were unchanged.

## Held-out confirmation
Five 20-second ordinary-GIL nested pairs with alternating artifact order, plus flat/mixed controls: 14 valid trials, 280 timed seconds. All original pair gates passed; every nested pair improved useful throughput and the predeclared >=1% median benefit gate passed. Median nested goodput gain: **4.841%**. Individual goodput / adjusted-p99 ratios:
- gil-nested-0: 1.046624 / 0.979323.
- gil-nested-1: 1.048411 / 0.960882.
- gil-nested-2: 1.053504 / 0.939320.
- gil-nested-3: 1.041458 / 0.970567.
- gil-nested-4: 1.055092 / 0.945416.

Flat and mixed confirmation controls also passed. These small, held-out same-host cohorts do not establish universal repeatability or production latency guarantees.

## Startup and memory tradeoff
- control: registration 296.661 us/route; first encode 15.012 us; second encode 14.301 us; retained traced Python bytes 12170.89/route.
- candidate: registration 575.757 us/route; first encode 13.650 us; second encode 12.625 us; retained traced Python bytes 22740.89/route.

This separate diagnostic uses 200 routes sharing one nested schema, warm shared caches, and an independent tracemalloc pass. The direct compiler adds registration CPU and retained code/guards while reducing repeated execution work. Traced Python bytes are not RSS, a peak or a universal per-schema bound. GIL binding happens once at registration, not per worker.

## Evidence accounting
38 complete valid timed trials; **12,360,850 exact replies**; zero bad/transport errors; every owned benchmark-server PID exited. The companion JSON retains all per-pair outcomes, raw-trial digests and wheel pins.

Raw manifests, native outputs, predeclarations, operation probes, oracle outputs, registration diagnostics and exact private wheel remain outside Git at `Projects/dexpot-performance/gil-nested-direct-20261022/` under the operator's home. They are retained for reanalysis; this sanitized summary is not a replacement for raw traces. No package release or website change is part of this experiment.
