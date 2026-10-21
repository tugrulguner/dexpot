# Completed-response handoff experiment

> Historical source generation: the unconditional-handoff failures below remain retained. A later owner-lifetime policy plus CPU-budget correction passed the original 16-connection gate and the final macOS FT artifact screen; see [the correction and exact measured scope](darwin-ft-owner-policy.md). This does not reinterpret the earlier results.

This is an **unmerged macOS free-threaded experiment**, not a release claim or a general scheduling recommendation.

## Mechanism and dependencies

After a successfully completed keep-alive response, the connection owner calls `os.sched_yield()` before processing another request. Startup binds selection from the actual runtime GIL state, Darwin platform, and function availability. Close/error paths do not yield. Connection ownership, admission permits, buffered requests, deadlines, validation, encoding, and fallback scheduling policy remain in place.

The measured candidate combines the isolated scalar preparation (#128), immutable path table (#130), thread-owned Darwin policy wrappers (#131), and direct nested preparation with fallback-only policy scope (#132). The handoff is the delta from combined commit `4e0aedc95f9553e2a558ffe263f0cf2ae5e870f8` to `9c7d6168e71e04eed457470f3bd796937b0c18a8`. It is not an independent measurement of each component.

## Installed artifact

- Candidate commit: `9c7d6168e71e04eed457470f3bd796937b0c18a8`.
- Wheel SHA256: `1a8daf4f0e36df14468ff0751f4b22a179b26f86b878c0bfd823e10e1062ce5d`.
- All 13 installed Python module files equal the clean committed source.
- Original control: `e703edf18d1526ebc2a91398f18c9e808e5cf5aa`.
- Fast control: `4e0aedc95f9553e2a558ffe263f0cf2ae5e870f8`.
- Clients and exact-body validator unchanged; no fixture-side handoff, forced GIL setting, profiler, QoS change, or power-setting change. AC Low Power Mode remains enabled.

## Results and limits

The 12-cell flat/nested capacity screen passed the original goodput, adjusted-p99, correctness, runtime-identity, and both-side resource gates. Nested goodput was 1.334x and 1.326x the original control, with adjusted p99 of 8.045 and 8.029 ms versus 11.925 and 11.982 ms. Relative to the faster experimental control, nested goodput was 0.957x and 0.941x, while adjusted p99 was approximately 0.52x. This is an explicit peak-throughput tradeoff, not dominance over both controls.

The original nested fixed-load check at 10,000 requests/s passed: candidate achieved 9,997 requests/s and scheduled p99 2.417 ms, within the retained 20 ms budget. All 14 planned trials completed, with 17,002,588 explicitly validated replies.

A separate mixed item/I/O/CPU campaign passed its two capacity/tail comparisons. Its 10,000/s fixed-load check **failed**: candidate scheduled p99 was 54.079 ms; the original control missed both rate and tail budgets (9,405 requests/s, 1,945.599 ms scheduled p99). The candidate's same-run uncorrected/actual-start p99 was 8.86 ms; this does not replace or clear its scheduled-latency failure, and subtracting these percentiles does not identify per-request queueing.

The historical mixed client cycles item/item/I/O/CPU requests. It does not provide measured class shares or per-class latency distributions. A separate reverse-order fast-versus-handoff fixed-load ablation completed all four trials. Both variants met the offered-rate requirement but failed the scheduled-p99 budget. Fast-control p99 was 38.207 and 39.999 ms; handoff p99 was 80.447 and 48.031 ms. Thus the mixed budget failure exists without the handoff, but unconditional handoff also worsened this workload in both pairs. This is adverse evidence against promoting unconditional handoff as a universal default; it does not replace the failed qualification trial.

No full performance qualification, cross-platform performance approval, merge, or release is established. Earlier losing and invalid results remain retained. Local Docker was unavailable, so no new Linux container measurement is claimed.

## One-factor concurrency diagnostic

With unchanged installed artifacts, native client, mixed profile, 10,000/s offered rate and 30-second duration, increasing connections from 16 to 32 brought scheduled p99 below 20 ms for both the fast control (10.303 ms) and handoff candidate (11.223 ms). Both met rate, exact-response, transport, calibration, identity and resource requirements. These two diagnostic records support sensitivity to available concurrency under this client/workload, not proof of a particular server or client queueing cause. They neither replace the original 16-connection failure nor qualify the handoff for promotion. Results are retained in `benchmarks/response_handoff/concurrency-diagnostic.json`.
