---
title: Execution model
description: How Dexpot schedules synchronous handlers on free-threaded and standard GIL CPython, including admission limits and process fan-out.
---

Dexpot chooses its scheduler once when the module imports. The request ownership and compilation path is traced in [Trace a request through Dexpot](/guides/request-lifecycle/). The application keeps the same synchronous handlers in every mode.

| Runtime | Default serving model | Overload behavior |
|---|---|---|
| Free-threaded CPython (`sys._is_gil_enabled() == False`) | One process; each admitted connection owns a thread | Active connections are capped at 1,024 by default; excess connections receive 503 before thread creation |
| Standard GIL CPython | A bounded pool of `CPU * 2 + 2` connection-owning threads | The queue is capped at `2 * pool`; excess connections receive 503 |
| Standard GIL CPython with `DEXPOT_WORKERS>1` | POSIX `SO_REUSEPORT` processes, each with its own bounded pool | Each worker sheds independently |

A worker owns a keep-alive connection until it closes. Idle keep-alive sockets are not returned to a shared admission queue.

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
