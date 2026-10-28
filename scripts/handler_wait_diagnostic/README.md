# Actual handler-wait diagnostic

This is an instrumented observation, not qualification. It preserves the original application, native client, validator, requested 1 ms sleep, 15-second mixed workload, four client threads, sixteen connections, and numerical/resource budgets. A startup sidecar records actual application `/io` sleep wall/thread-CPU durations before route compilation. No OS policy or GIL interval is changed. Wall minus CPU does not identify an OS or GIL cause.

The controller needs the original harness dependencies (`psutil`); server interpreters must already contain the exact corresponding wheel and dependencies. The original harness `PROBE` verifies installed package bytes against each wheel. A failed run retains its files; output directories cannot be reused. Native error counters, serving PID, collector counts/drops, exact requested waits, workload/validator/wheel fingerprints and unchanged resource budgets are checked. Up to sixteen final in-flight sleep calls beyond validated replies are recorded explicitly, never silently discarded.

```sh
python scripts/handler_wait_diagnostic/run.py \
  --harness scripts/lifecycle_preflight_harness/run.py \
  --collector scripts/handler_wait_diagnostic/collector \
  --original-python "$ROOT/main-gil/bin/python" \
  --original-wheel "$ROOT/dist-main/dexpot-0.7.1-py3-none-any.whl" \
  --current-python "$ROOT/pr-gil/bin/python" \
  --current-wheel "$ROOT/dist-pr/dexpot-0.7.1-py3-none-any.whl" \
  --wrk "$(command -v wrk)" --output "$NEW_OUTPUT"
python scripts/handler_wait_diagnostic/run.py --audit-only "$NEW_OUTPUT"
```

The collector uses role-specific exclusive output files and only dumps from `application.py`, not startup identity helpers. Neither a passing observation nor large actual sleep durations clear any retained performance failure. The hosted workflow uses the same macos-26 runner class as the failed matrix, not the same physical machine. It refuses workflow retries.
