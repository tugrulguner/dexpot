---
title: Benchmark without overclaiming
description: A correctness-first procedure for measuring Dexpot with wrk while separating client-observed latency from framework time.
---

Dexpot makes interpreter-adaptive execution a design goal, but this repository does not establish a universal speedup over other frameworks. A single machine, one run, or an invalid-response count alone is not comparative evidence. The recorded [loopback example](/playground/) is explicitly exploratory and client-observed; do not generalize its numbers to production or framework processing time.

## Define the question and boundary

Before measuring, record the question (for example, sustainable successful requests at a target latency), Python build and GIL state, Dexpot revision, OS/hardware, parser mode, pool/queue/worker settings, route/body, generator version and settings, duration, warm-up, and repetition plan. State whether latency includes client scheduling, TCP loopback, HTTP parsing, routing, handler execution, encoding, and response transfer. `wrk` client latency includes its own scheduling and transport; it is not isolated server CPU time.

Compare only equivalent work: same response status and bytes, request method/body, connection policy, concurrency, keep-alive, runtime/build, host conditions, and validation. Include successful-response correctness checks; a fast server returning wrong or missing bodies is not a valid result.

## Run a correctness-matched local experiment

Use the checked-in [`minimal.py`](https://github.com/tugrulguner/dexpot/blob/main/examples/minimal.py) and the repository's [`dexpot-loopback.lua`](https://github.com/tugrulguner/dexpot/blob/main/website/benchmarks/dexpot-loopback.lua) validator. The script requests GET `/items/7` and checks status 200 plus the exact body `{"id":7,"name":"item-7","price":7.0}`; mismatched status or body increments the invalid count.

```bash
uv sync --all-extras
DEXPOT_HTTP_PARSER=python DEXPOT_EXAMPLE_PORT=8000 uv run python examples/minimal.py
# In a second terminal, from the repository root:
wrk -t2 -c16 -d30s --latency -s website/benchmarks/dexpot-loopback.lua http://127.0.0.1:8000
```

Repeat with a fixed, disclosed matrix and independent runs; retain raw output and report errors alongside latency distributions and throughput. Stop unrelated local load. Do not present the connection count or test duration as production capacity. For cross-framework claims, publish equivalent application and generator code plus environment, exact versions, commands, raw results, and correctness validation. Prefer omitting a comparative claim when the workloads or measurement boundaries cannot be matched.

## Interpret scheduler and parser experiments

Record `sys._is_gil_enabled()` where available and the exact Python build; distinguish a standard GIL build from a free-threaded build. Report `DEXPOT_POOL`, `DEXPOT_MAX_QUEUE`, `DEXPOT_MAX_CONNECTIONS`, and `DEXPOT_WORKERS`. Queue and active-connection capacity are per process except the free-threaded active-connection semaphore, which is process-wide within the single process. A worker fan-out multiplies per-worker GIL capacity; it is not a single global queue.

Compare `DEXPOT_HTTP_PARSER=python` and `native` only when the optional extension is installed and both produce identical accepted/rejected behavior. The native extension parses request heads only; it does not move sockets or handler work to Rust. Parser throughput alone is not whole-server throughput.

The existing loopback record is one exploratory 5-second run with its own stated boundary, not a regression threshold or reproducible cross-product benchmark. See the [execution model](/execution-model/) for what the selected scheduler actually does.

[Download this guide as Markdown](/guides/benchmarking.md).
