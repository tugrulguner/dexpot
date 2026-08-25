# dexpot roadmap

dexpot is building a synchronous Python API framework around one runtime fact:

```text
plain Python handlers
+ compiled route and codec plans
+ connection-owning threads
+ interpreter-adaptive admission
= predictable HTTP execution on GIL and free-threaded CPython
```

The framework owns the HTTP server, routing, validation, scheduling, overload behavior, and
graceful shutdown. It is not an ASGI wrapper and will not require application authors to
maintain async and sync versions of the same endpoint.

## Shipped foundation

The current release line provides:

- `GET`, `POST`, `PUT`, `PATCH`, and `DELETE` route decorators.
- Literal and parameterized routes with structural duplicate detection.
- Registration-time compilation of path, body, default, positional, and keyword-only
  handler bindings.
- Registration-time rejection of unbound captures and variadic handlers.
- Integer path conversion with 422 failures.
- msgspec JSON body decoding and validation into `Struct` types.
- msgspec response encoding and `(status, payload)` handler returns.
- HTTP/1.1 keep-alive with one connection owned by one worker until close.
- Automatic free-threaded detection through `sys._is_gil_enabled()`.
- One-process thread-per-connection execution on free-threaded CPython.
- Bounded GIL thread pools with queue limits and immediate 503 shedding.
- Optional POSIX `SO_REUSEPORT` worker processes on GIL builds.
- Worker restart, partial-startup cleanup, SIGINT/SIGTERM handling, and bounded draining.
- A CLI for loading `module:attribute` applications.
- Installable coding-agent guidance for six agent formats.
- Python 3.12–3.14 and 3.14t CI, static checks, package builds, and real HTTP tests.

## Next milestones

The sequence reflects safety and technical dependencies, not promised dates.

### 1. HTTP correctness and hostile-input limits

Make the socket core safe to expose before broadening the framework API:

- Bound request-line, header-count, header-size, body-size, and idle-read time.
- Reject malformed `Content-Length`, conflicting length headers, unsupported transfer
  encodings, invalid request targets, and incomplete bodies with stable 4xx responses.
- Define HTTP/1.0 and HTTP/1.1 keep-alive semantics explicitly.
- Add method-not-allowed handling and distinguish 404 from 405.
- Percent-decode paths safely and define duplicate-slash and trailing-slash behavior.
- Stop returning raw handler exception messages to clients; add stable public failures and
  server-side diagnostics.
- Test slow clients, disconnects, pipelining, oversized input, queue saturation, and drain
  deadlines with real sockets.

### 2. Complete endpoint and response contracts

Turn the serving core into a useful application framework without inflating decorators:

- Make request context available through a small typed API: method, path, path parameters,
  query parameters, headers, validated body, and client metadata.
- Add typed query/header/cookie binding with registration-time validation.
- Enforce declared response types instead of treating `response=` as an encoder hint.
- Add first-class status codes, response headers, empty responses, and stable error types.
- Generate OpenAPI from the same compiled endpoint plans used by traffic.
- Add middleware and lifecycle hooks with explicit ordering and no hidden async bridge.
- Define dependency injection around plain factories and request/application scopes, not a
  large decorator parameter surface.

### 3. Performance evidence and scheduler evolution

Keep optimization evidence reproducible and correctness-equivalent:

- Publish a versioned `benchmarks/` harness using `wrk`, fixed request mixes, and equivalent
  validation and response behavior across frameworks.
- Report successful responses, errors, p50/p95/p99 latency, and CPU/memory—not RPS alone.
- Benchmark native GIL and free-threaded interpreters in separate environments and record
  `sys._is_gil_enabled()` with every result.
- Sweep GIL pool, queue, and process counts instead of selecting a flattering competitor
  configuration.
- Profile route matching, parsing, codec use, allocations, locks, and system calls before
  introducing native code.
- Add deterministic overload tests that prove useful work stays responsive while excess
  connections receive 503.
- Evaluate a compiled parser only after Python-level measurements identify parsing as the
  limiting layer.

### 4. Production operations

Add operational controls while preserving the synchronous programming model:

- Structured access and error logging with request IDs.
- Metrics for active connections, queue depth, saturation, worker restarts, response status,
  and drain duration.
- Configurable graceful-shutdown and per-connection deadlines.
- Trusted-proxy and forwarded-header policy.
- TLS guidance and explicit reverse-proxy deployment patterns.
- Health/readiness hooks that distinguish a live process from an accepting worker set.
- Stable configuration objects and environment-variable validation at startup.
- Linux and macOS multiprocess hardening; define an honest Windows strategy before claiming
  multiprocess support there.

### 5. Framework ecosystem

Once the contract and operations are stable:

- Progressive runnable examples under `examples/` for each supported use case.
- Extension points with compatibility tests and a documented stability policy.
- Framework-level database/session lifecycle integrations that remain synchronous.
- Test clients and fixtures built on the real HTTP surface rather than a separate dispatcher.
- Deployment recipes and performance baselines for supported Python/runtime combinations.

## Non-goals

- Requiring `async def`, exposing an event loop API, or making ASGI the framework core.
- Becoming a thin wrapper around FastAPI, Starlette, Flask, or another server.
- Hiding GIL versus free-threaded behavior behind one misleading performance number.
- Accepting unbounded work on GIL builds instead of shedding overload.
- Adding complex decorator configuration when a small typed object or ordinary Python
  function can express the same contract.
- Claiming production readiness before parser limits, stable failures, operational signals,
  and representative soak tests exist.

## Design invariants

```text
registration compiles; requests execute
```

```text
one live keep-alive connection = one owning worker
```

```text
free-threaded Python uses threads for parallelism
GIL Python uses bounded threads and optional process fan-out
```

A future parser, middleware system, or dependency layer may optimize the implementation. It
must not introduce coroutine requirements, move declaration errors into live traffic, or
silently weaken overload and shutdown behavior.

---

Roadmap work should get a focused issue before implementation. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) and include a real-user HTTP test for behavior changes.
