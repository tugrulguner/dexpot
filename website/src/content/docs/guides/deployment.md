---
title: Deploy within current boundaries
description: Select Dexpot's interpreter-specific scheduler, size bounded admission, operate shutdown, and keep unsupported edge responsibilities outside the alpha framework.
---

**Status:** Dexpot is alpha and is not yet recommended for untrusted production traffic. Read [current boundaries](/current-boundaries/) before adoption. This guide explains shipped process behavior; it does not add TLS, middleware, authentication, proxy-header trust, or a hardened deployment mode.

## Select the serving model

The scheduler branch is selected at import time from the interpreter's GIL state. Configure environment values before starting the process (and before any importing launcher initializes Dexpot).

| Runtime | Default model | Capacity and overload |
|---|---|---|
| Free-threaded CPython | One process; one thread per admitted connection | `DEXPOT_MAX_CONNECTIONS=1024` process-wide active-connection cap; excess admission receives 503 before creating a thread |
| Standard GIL CPython | Bounded pool of connection-owning threads | `DEXPOT_POOL=0` means automatic `CPU * 2 + 2`; `DEXPOT_MAX_QUEUE=2 * pool`; excess queued work receives 503 |
| Standard GIL CPython, POSIX workers | `DEXPOT_WORKERS=N` processes, each with its own bounded pool | Each worker sheds independently; the local capacities multiply across workers |

These limits bound admitted connections or queued work, not request rate or total memory. Each worker owns a keep-alive connection until it closes; idle live connections are not recycled through a shared queue. Free-threaded execution remains single-process. Multiple workers require POSIX `fork` and `SO_REUSEPORT`.

## Set and validate capacity

```bash
# GIL process; values are per process
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app --host 127.0.0.1 --port 8000

# Free-threaded build: cap admitted connections
DEXPOT_MAX_CONNECTIONS=512 dexpot serve main:app --host 127.0.0.1 --port 8000

# Optional GIL-only POSIX fan-out
DEXPOT_WORKERS=4 DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app
```

`DEXPOT_POOL=0` requests automatic sizing. Negative pool values and nonpositive queue or connection caps fail during import, before the listener opens. `DEXPOT_WORKERS` defaults to one; values greater than one are rejected when the required POSIX facilities are unavailable. See the executable contract in [`app.py`](https://github.com/tugrulguner/dexpot/blob/main/src/dexpot/app.py) and [`test_http_hardening.py`](https://github.com/tugrulguner/dexpot/blob/main/tests/test_http_hardening.py).

## Own the network boundary

The server listens on loopback by default. Bind publicly only behind an explicitly configured TLS-terminating proxy or other network boundary that you operate. Dexpot itself does not terminate TLS, authenticate, implement middleware, or define a trusted proxy-header policy. Do not treat `X-Forwarded-*` values as trusted identity or client-address data without an external trust policy.

Configure `HttpLimits` to match the application rather than assuming that parser defaults fit every workload. Defaults are documented in the [HTTP boundary](/http-boundary/); limits and deadlines are positive and immutable. Dexpot supports validated `Content-Length`, not chunked transfer encoding. Unsupported `Expect` requests receive 417 before body reads; oversized inputs and deadline failures close the connection. HEAD responses contain no body after parsing, including error paths (admission can reject before the method is read).

## Stop and supervise

SIGINT and SIGTERM stop admission and allow active connections up to five seconds to drain. The GIL-mode supervisor restarts an unexpectedly exited worker. Multiprocess serving is POSIX-only; the current Windows configuration is single-process. Exercise process shutdown and listener closure in subprocess tests; serving in a helper thread is not a valid signal test. See [`test_multiprocess.py`](https://github.com/tugrulguner/dexpot/blob/main/tests/test_multiprocess.py).

For parser selection (`python`, `native`, `auto`) and framing rejection details, read [HTTP boundary](/http-boundary/). For route and handler limitations, see [current boundaries](/current-boundaries/).

[Download this guide as Markdown](/guides/deployment.md).
