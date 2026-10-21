---
title: Execution model
description: How Dexpot schedules synchronous handlers on free-threaded and standard GIL CPython, including admission limits and process fan-out.
---

Dexpot chooses its scheduler when `serve()` starts, after application imports, using the actual GIL state. A free-threaded build with the GIL enabled uses the GIL serving model. Later GIL changes are reported without switching the running scheduler; restart after loading dependencies to select the new mode. The request ownership and compilation path is traced in [Trace a request through Dexpot](/guides/request-lifecycle/). The application keeps the same synchronous handlers in every mode.

| Runtime | Default serving model | Overload behavior |
|---|---|---|
| Free-threaded CPython (`sys._is_gil_enabled() == False`) | One process; each admitted connection owns a thread | Active connections are capped at 1,024 by default; excess connections receive 503 before thread creation |
| Standard GIL CPython | A bounded pool of `CPU * 2 + 2` connection-owning threads | The queue is capped at `2 * pool`; excess connections receive 503 |
| Standard GIL CPython with `DEXPOT_WORKERS>1` | POSIX `SO_REUSEPORT` processes, each with its own bounded pool | Each worker sheds independently |

A worker owns a keep-alive connection until it closes. Idle keep-alive sockets are not returned to a shared admission queue.

## Worker lifecycle

This diagram is a lifecycle explanation, not a performance chart. It supplements the existing conceptual execution overview and response-contract illustration.

<figure>
  <a href="/dexpot-worker-lifecycle.webp?v=071-lifecycle-v1" aria-label="Open the worker-lifecycle diagram at full size">
    <img loading="lazy" decoding="async" width="2400" height="1800" src="/dexpot-worker-lifecycle.webp?v=071-lifecycle-v1" alt="Dexpot worker lifecycle: actual GIL selection at serve startup, macOS FT worker policy, completed-response CPU fairness and capacity reclaimed after owner exit." />
  </a>
  <figcaption><a href="/dexpot-worker-lifecycle.webp?v=071-lifecycle-v1">Open the worker-lifecycle diagram at full size</a>. The same lifecycle is described below.</figcaption>
</figure>

1. **Bind once at serving startup.** Application imports complete before `serve()` selects the scheduler from the actual GIL state. A free-threaded interpreter whose GIL is enabled uses the GIL path. Admission-limit environment values are still read and validated during import; startup mode selection is a separate decision.
2. **Admit a bounded FT connection owner.** Reserve capacity before starting its worker. That worker owns the connection through keep-alive and cleanup. Linux also retains this bounded FT ownership model.
3. **Scope the macOS policy to the owner.** On actual free-threaded macOS, an available scheduling policy may be saved and changed for that owner only. The main/acceptor thread policy is unchanged. Unavailable or unsuccessful setup falls back; exceptions still clean up the registered connection. Successful policy changes are restored before the worker exits, and restoration failures are surfaced.
4. **Share CPU at completed-response boundaries.** On the selected macOS FT handoff path, accumulate actual thread CPU time. After a successfully completed response that keeps the connection open, offer other workers a turn once at least 1 ms has accumulated. Elapsed waiting does not spend this budget. A handler is never preempted by this mechanism; close/error paths do not yield as though another response were due. Linux and GIL-enabled execution do not enable these Darwin policy/handoff hooks.
5. **Finish ownership before reclaiming capacity.** Close the connection, restore any successfully changed worker policy, and let the owner thread finish. The reaper joins it and releases its capacity slot only after the thread has exited. Closing a socket alone does not make a still-running worker's slot reusable.

See the [deployment guide](/guides/deployment/) for configuration and the [owner-policy qualification report](https://github.com/tugrulguner/dexpot/blob/main/docs/darwin-ft-owner-policy.md) for experiments and limits. The diagram makes no new latency or cross-platform performance claim.

## Tune admission

Set limits before the process imports Dexpot:

```bash
# Free-threaded process-wide active-connection cap
DEXPOT_MAX_CONNECTIONS=512 dexpot serve main:app

# Standard GIL pool and queue
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app
```

`DEXPOT_POOL=0` keeps automatic sizing. Negative pool sizes and nonpositive queue or connection limits fail during import, before a listener can open.

## Process fan-out

On supported POSIX systems:

```bash
DEXPOT_WORKERS=4 dexpot serve main:app
```

`DEXPOT_WORKERS>1` requires POSIX `fork` and `SO_REUSEPORT`. Dexpot rejects the setting on unsupported platforms. Free-threaded builds intentionally remain single-process because their threads can execute Python in parallel.

## Shutdown and supervision

SIGINT and SIGTERM stop admission and allow active connections up to five seconds to drain. The standard-GIL supervisor restarts a worker that exits unexpectedly.

## Compiled plans

Registration produces immutable `EndpointPlan` objects for binding, path conversion, and body and response codecs. Serving freezes those endpoints into one `ApplicationPlan` and a length-grouped `RouterPlan` before opening a listener. Late route registration fails instead of diverging from the plan traffic uses.

The [execution map](/dexpot-execution.webp?v=070-response-v1) follows the full ownership path: registration, interpreter-specific scheduling and connection admission, request-head parsing, route matching and binding, the synchronous handler, and response preparation/encoding. In automatic parser mode a compatible optional Rust/PyO3 parser handles the bounded request head; Python mode forces the reference, and automatic mode falls back to Python when native is absent. A broken or incompatible native installation remains visible.
