# Darwin free-threaded owner scheduling correction

## Mechanism and ownership

The completed-response CPU budget alone did not correct the mixed-workload scheduled-latency failure. A server-only HTTP trace measured long I/O-handler wall times with little CPU use. In an isolated owned subprocess, ordinary → fixed → ordinary `THREAD_EXTENDED_POLICY` controls reversibly changed the p99 of the unchanged 1 ms wait from about 9 ms to 1.3 ms and back. This establishes a worker-policy contribution in that probe, not a causal decomposition of an earlier client percentile.

Dexpot selects its existing Darwin policy adapter after application loading, only for actual free-threaded Darwin serving. Each connection owner reads its own policy, switches ordinary policy `1` to fixed policy `0` when possible, executes the existing ownership loop with the 1 ms accumulated-thread-CPU completed-response handoff, and restores its prior policy before exit. Already-fixed, unavailable, and unsuccessful initial transitions retain their existing behavior. Restoration failure is explicit. Unexpected policy-setup exceptions close/remove the registered connection and notify drain waiters before escaping.

Main/acceptor policy, admission, permit reclamation after join, buffers, deadlines, handler semantics, validation and parser boundaries remain unchanged. No host power setting or QoS class is changed. The quantum is checked at response boundaries; it is not hard preemption of an individual handler.

## Final installed-artifact qualification

Measured source: `0390037ccdab1a4cba0ac0039bcc44d1886d5017`.
Installed wheel SHA256: `908611b25867ae8a21d977176a16b34fab111a5443b46a84cbfa4294355e3e18`.
All 13 installed Python modules matched committed source. Every trial verified serving-time GIL-disabled state, actual worker policy `0` for the candidate versus `1` for controls, main/acceptor policy `1`, unchanged source/client fingerprints, exact responses, transport and resource budgets. Before/after power configuration was identical.

The final macOS FT matrix completed **18/18 valid trials**, each 30 seconds, with **16,597,298 exact validated replies**. Capacity uses native closed-loop wrk-adjusted p99; fixed load uses native wrk2 scheduled-send latency. Capacity ratios below compare with the original acceptance control, not the later fast artifact. Both orders are retained:

- Flat capacity: **1.941× / 2.000×** useful throughput; adjusted p99 ratios **0.967 / 0.907**. Original flat screen passed.
- Nested capacity: **1.476× / 1.425×** useful throughput; adjusted p99 ratios **0.320 / 0.394**. Original nested screen passed.
- Mixed capacity: **4.677× / 4.663×** useful throughput; adjusted p99 ratios **0.145 / 0.145**. Capacity and relative-tail gates passed.
- Original mixed fixed load, **10,000 requests/s, 16 connections**: candidate scheduled p99 **3.149 / 2.963 ms**, versus fast-control **36.351 / 31.263 ms**. Both candidate rate and unchanged **20 ms** tail budgets passed.
- Nested fixed load, same rate/concurrency: candidate scheduled p99 **2.551 ms**, original control **2.407 ms**; both rate/tail budgets passed.

Raw per-trial commands, metrics, client output, fingerprints, runtime evidence, resources, frozen gates, power snapshots and source-review records are retained in [`installed-owner-screen.json`](../benchmarks/response_handoff/installed-owner-screen.json).

## Correctness and review

Final runtime source passed `make check build`: **589 passed, 25 skipped**, lint/format/typecheck, 81.12% coverage and wheel/sdist build. Actual unforced Python 3.14t passed **603 tests, 11 skipped**, with checkout import identity and GIL-disabled assertions at session start/finish. The setup-exception regressions failed with real open registered sockets before repair, then passed. A real FT HTTP probe confirmed handler policy `0`, unchanged main/acceptor policy `1`, restoration to `1` before worker exit, HTTP 200 and the 1 ms diagnostic. Independent source-only owner-policy and cleanup-delta reviews found no concrete issues; these are not independent performance executions.

## Retained failures and limits

Earlier unconditional-handoff, CPU-budget-only and concurrency-diagnostic results remain retained and valid for their source generations. The passing final 16-connection trials do not erase those failures or turn a 32-connection diagnostic into qualification. The earlier history is in [the handoff experiment](completed-response-handoff-experiment.md).

This is a macOS FT, 30-second paired installed-artifact screen, not a long production soak, per-class mixed-tail study, competitor-leadership claim, or cross-platform performance qualification. No new Linux performance run is claimed. Remote multi-platform correctness/build CI is a separate gate. This branch stacks the compiler/path/native-policy preparation changes; these ratios do not isolate the owner-policy delta alone. Nothing is merged or released by this report.
