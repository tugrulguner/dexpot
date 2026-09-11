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

The performance strategy spans both interpreter modes: bounded concurrency and optional
process fan-out for standard GIL builds, real parallel threads for free-threaded builds,
compiled C-backed codecs, and evidence-gated Rust acceleration for narrow hot paths. The
developer workflow is agent-ready too: bundled coding-agent skills track the same shipped
route contract and runtime boundaries as the framework documentation.

## Performance and simplicity objective

The goal is to become the fastest, most resource-efficient modern Python API framework on
both GIL-enabled and free-threaded CPython, with the smallest practical API and execution
model. This is an engineering objective, not a claim of current benchmark leadership.
Measure correct useful throughput within declared latency and resource budgets; neither fast
rejections nor unchecked responses establish equivalent performance.

Keep ordinary synchronous functions, registration-time direct calls, immutable serving plans,
conditional feature allocation, and the parser-only native boundary. Prefer removing shared
state and duplicate work over adding abstraction layers. New complexity must earn its place
through representative measurements on both interpreter modes.

## Shipped foundation

The current release line provides:

- `GET`, `POST`, `PUT`, `PATCH`, and `DELETE` route decorators.
- Literal and parameterized routes with structural duplicate detection.
- Registration-time compilation of path, body, default, positional, keyword-only, and Request
  bindings into endpoint-specific direct `invoke` callables.
- Serving-time freeze into an immutable `ApplicationPlan`, length-indexed `RouterPlan`, and
  complete `EndpointPlan` metadata before a listener opens.
- Registration-time rejection of unbound captures and variadic handlers.
- Integer path conversion with 422 failures.
- msgspec JSON body decoding and validation into `Struct` types.
- Typed public `Request` injection through endpoint-specific direct invokers. A frozen, GC-tracked
  msgspec object is constructed only for Request-aware endpoints and exposes method, path, raw path
  parameters, raw query, headers, raw body, and the already validated body without a facade.
- msgspec response encoding and `(status, payload)` handler returns.
- HTTP/1.1 keep-alive with one connection owned by one worker until close.
- Bounded HTTP/1.0 and HTTP/1.1 request parsing with configurable request-line, header, body,
  idle-read, and absolute head/body deadlines.
- Fail-closed request framing, strict path decoding, explicit slash behavior, and 404/405
  method resolution.
- Stable public parser and handler failures with server-side exception diagnostics.
- Automatic free-threaded detection through `sys._is_gil_enabled()`.
- One-process thread-per-connection execution on free-threaded CPython.
- Bounded GIL thread pools with queue limits and immediate 503 shedding.
- Optional POSIX `SO_REUSEPORT` worker processes on GIL builds.
- Worker restart, partial-startup cleanup, SIGINT/SIGTERM handling, and bounded draining.
- A CLI for loading `module:attribute` applications.
- Installable coding-agent guidance for six agent formats.
- Python 3.12–3.14 and 3.14t CI, static checks, package builds, and real HTTP tests.
- A pure-Python reference request-head parser plus an optional parser-only `dexpot-native`
  source subproject with import-time automatic selection.
- Differential parser parity, deterministic mutation and concurrency tests, `cp312-abi3`
  standard wheels, and version-specific `cp314t` wheel CI across supported platforms.

## Completed milestones

The sequence reflects safety and technical dependencies, not promised dates.

### 1. HTTP correctness and hostile-input limits

The socket core now establishes the bounded, fail-closed foundation required before broadening
the framework API:

- Bound request-line, header-count, header-size, body-size, idle-read time, and absolute
  head/body duration.
- Reject malformed `Content-Length`, conflicting length headers, unsupported transfer
  encodings, invalid request targets, and incomplete bodies with stable 4xx responses.
- Define HTTP/1.0 and HTTP/1.1 keep-alive semantics explicitly.
- Add method-not-allowed handling and distinguish 404 from 405.
- Percent-decode paths safely and define duplicate-slash and trailing-slash behavior.
- Stop returning raw handler exception messages to clients; add stable public failures and
  server-side diagnostics.
- Test slow clients, disconnects, pipelining, oversized input, queue saturation, and drain
  deadlines with real sockets.

### 2. Optional native request-head seam

The repository now includes the narrow native seam validated in
[issue #18](https://github.com/tugrulguner/dexpot/issues/18):

- Keep the Python parser as the semantic reference and fallback. Import-time `auto` selection
  uses native only when a compatible separately installed extension is present.
- Keep Rust parser-only: Python owns sockets, limits, deadlines, body reads, pipelining,
  target decoding, routing, handlers, scheduling, and supervision.
- Build `dexpot-native` as a separate distribution, with one `cp312-abi3` wheel per standard
  platform and architecture plus version-specific free-threaded wheels such as `cp314t`.
- Run the direct differential corpus, deterministic mutation tests, concurrent parser stress,
  clean-wheel integration, and complete HTTP suite across standard and free-threaded CPython.
- Surface ABI, initialization, transitive-import, and parser API-version failures instead of
  silently changing behavior through the fallback.

The source subproject and its CI gates are complete. The accelerator is not yet published,
and it is not a default dexpot dependency.

## Next milestones

The research-backed sequence below separates reproduced correctness/simplicity concerns from
optimization hypotheses. Benchmark baselines, protocol maintenance, and resource limits run
alongside these milestones, not only after feature expansion. An open implementation or a
local experiment does not make a planned contract part of the shipped foundation.

### 3. Complete endpoint and response contracts

Extend the existing `ApplicationPlan`, `RouterPlan`, and `EndpointPlan` kernel without a
second dispatcher, live route mutation, or a larger decorator language. Deliver this work in
focused stages:

#### 3.1 Registration ownership and diagnostics

- Pass route-local body/response options directly into endpoint declarations rather than
  storing them on shared user functions; publish only complete registrations.
- Remove the process-global annotation-result cache and resolve annotations per registration.
  Preserve the separately bounded generated-call-shape cache and direct-invocation path.
- Preserve explicit annotation namespaces. Handle eager, stringified, and Python 3.14 deferred
  annotations deliberately; do not revive caller-frame guessing.
- Reject detectable unsupported coroutine handlers and signatures before serving.

Exit evidence: reuse across applications, failed-registration atomicity, retention and stale
annotation regressions, wrapped/local aliases, concurrent registration, and unchanged HTTP
binding behavior on both interpreter modes.

#### 3.2 Request-aware response handling and output policy

Local response-size and HTTP experiments identify recursive Request-aware response traversal
as a priority bottleneck, including poor free-threaded scaling in the tested cases. These are
diagnostic findings, not a competitor ranking or a qualified replacement design. Earlier
constructor measurements do not settle complete request/response cost.

- Compare an experimental specialized traversal intended to preserve compatibility with a
  GC-enabled opaque context prototype. Keep Request allocation conditional and already parsed
  wire values shared within their request lifetime.
- Test dictionaries and typed Structs, fresh and shared payloads, response sizes, and thread
  counts. Profile generic inspection and shared-object costs before attributing FT contention.
- Require nested-container, custom-hook, cycle, logging, and compatibility tests before changing
  Request representation. Do not remove protections or disable GC simply to improve a score.
- Define response validation, coercion, public-field projection, and serialization separately.
  A malformed same-type or nested Struct must not bypass a promised checked contract.
- Consolidate status codes, headers, empty responses, sanitized errors, and explicit raw-output
  escape hatches. Preserve or explicitly migrate existing tuple-response behavior.

Exit evidence: full response-contract corpus, a representation/migration decision, no
requestless allocation regression, and repeatable GIL/FT end-to-end results. Opaque context and
specialized traversal remain hypotheses until these gates pass.

#### 3.3 Paired lifecycle and typed input sources

- Add one synchronous paired acquisition/cleanup mechanism with reverse-order teardown and
  partial-startup rollback before accepting traffic.
- Distinguish process/application, worker/thread, connection, and request lifetimes. A leased
  database connection need not have the sharing rules of its pool; a process-local singleton
  is not shared state across workers.
- Extend request context with lazy decoded query/cookie views and explicitly sourced client
  metadata. Define repeated values, missing versus null, and trusted-proxy behavior.
- Add typed query/header/cookie binding with explicit ambiguity resolution and registration-time
  validation, keeping ordinary Python functions and annotations central.
- Generate OpenAPI from the same normalized endpoint metadata and msgspec schemas used by
  traffic, not a second introspection pipeline.

Exit evidence: runnable examples under `examples/` for typed CRUD, pagination/repeated values,
header authentication, transaction failure, outbound blocking I/O, custom response headers,
and invalid outputs; runtime/schema agreement and exact acquire/use/cleanup traces.

#### 3.4 Optional hooks and scoped factories

- Start with ordinary factories and closures; add scoped dependency machinery only when real
  examples demonstrate a need.
- Compile applicable hook chains and any required dependency graph at registration. Keep
  no-hook/no-dependency routes free of generic runtime machinery and allocate cleanup state
  only where needed.
- Define request-local memoization, ordering, overrides, and cleanup on handler/encoding failure.
  Commit failures that must affect HTTP success need to occur before response transmission.
- Reset ambient request context per request, including keep-alive and worker reuse. Do not
  depend on different GIL/FT thread-context inheritance defaults.
- Keep async bridges, large provider hierarchies, and per-route threading switches out of the
  ordinary application model. Disconnecting a socket does not safely cancel a Python thread.

Exit evidence: exact resource/cleanup traces, actionable diagnostics, real examples, and
measured zero-feature cost. Streaming requires its own lifetime/backpressure contract before
being included in these guarantees.

#### Request execution spike findings

The completed local Request representation and invocation spike compared manual slots, tracked and
untracked `msgspec.Struct` state, and a separate public facade on CPython 3.12, 3.14, and
free-threaded 3.14t:

- Generated direct invokers reduced the isolated call layer by 51–56% for no-argument handlers
  and 62–67% for one-path-parameter handlers.
- Positional tracked msgspec construction was approximately 90% cheaper than the then-current
  keyword-constructed frozen dataclass in the isolated benchmark.
- Five-round response-validating HTTP campaigns found no material default-route regression. The
  tracked and untracked msgspec variants led or tied the Request-aware free-threaded cells, while
  standard-CPython differences remained within campaign noise.
- A facade preserved a stricter public/internal boundary but added a second object on
  Request-aware routes and did not establish an end-to-end advantage.
- `gc=False` remains rejected for the initial implementation: its small constructor win was not
  consistent end to end and does not yet justify future cycle risk.
- Request construction and handler injection remain Python-owned. No Rust/PyO3 work is planned
  for this layer without a profile identifying a narrow native seam and equivalent-workload
  end-to-end evidence that it wins.

These macOS measurements informed the direct invokers and conditional, GC-tracked Request
construction shipped in v0.4.0; they are not public performance claims. Broader performance
claims and native promotion remain gated on complete contract and native-parser parity checks,
allocation and retention profiling, longer bare-metal Linux campaigns, and unchanged 404/405,
overload, memory, and shutdown behavior.

### 4. Performance evidence and scheduler evolution

Start the baseline before optimizing or broadening contracts, then repeat it as contracts evolve:

- Separate normal product facilities, equivalent-feature services, controlled-codec experiments,
  and best deployable stacks. Do not compare unchecked encoding to validated/filtered output
  without identifying the contract difference.
- Include FastAPI, Starlette, Litestar, Falcon, Robyn, BlackSheep, Sanic, aiohttp, and socketify.py.
  Include strong Falcon WSGI/threaded-server and msgspec-equipped configurations, Litestar's
  supported inline/offload choices, and tuned GIL process counts—not only convenient defaults.
- Pin framework/server/parser/codec/interpreter versions and resource budgets. Record actual
  worker `sys._is_gil_enabled()` after imports and warmup; mark unverified deployment cells
  honestly rather than assuming a wheel or executable name establishes FT support.
- Measure requestless and Request-aware JSON, typed bodies and checked outputs, first/last/miss
  routing at realistic route counts, real database/outbound I/O, pure-Python and native CPU
  work, mixed traffic, slow clients, overload/recovery, and shutdown.
- Report correct business goodput, error counts, successful-response tail latency, CPU, memory,
  thread/fd counts, and queue age. Fast 503s are not successful operations.
- Use `wrk` for saturation diagnostics and an arrival-scheduled generator for latency/SLO
  qualification. Account for coordinated omission, calibration, client validation overhead,
  and generator saturation; short local runs are not promotion evidence.
- Use randomized paired trials, separate tuning from held-out confirmation, retain every trial
  and invalidation reason, and report uncertainty and losing cells. Do not average percentiles
  into a fictitious pooled distribution or hide a losing runtime in a combined score.
- Normalize total CPU/memory and database-pool budgets across thread/process deployments.
  Require longer bare-metal Linux runs, real-service workloads, soak, and independent
  reproduction before broad performance claims.
- Profile routing, generic object inspection, allocation/retention, shared-state contention,
  parsing, codecs, and syscalls before selecting a change. Evaluate method/path and prefix
  indexes while retaining literal lookup and existing route precedence.
- Establish explicit FT connection/work budgets, including a configurable process-wide
  active-connection cap with explicit overload behavior before per-connection thread creation.
  Require real-socket coverage for slow keep-alive clients, thread growth, and file-descriptor
  pressure; measure idle-connection fairness and queue waiting time. Preserve one owner at a time;
  reconsider idle-socket scheduling only if measured resource/SLO failures justify it.
  Unbounded FT threads are not the production destination.
- Preserve the issue #18 parser parity and goodput gates; moving additional work into native
  code requires measured end-to-end benefit and supported GIL/FT artifacts.

Exit evidence: a correctness-matched baseline and reproducible qualification manifest, zero
observed semantic mismatches in the acceptance corpus, bounded resource recovery, and a
meaningful repeatable benefit without material regressions in mandatory workloads. Agree
quantitative budgets before confirmation rather than choosing them after seeing results.

A future publishable benchmark harness and results require their own reviewed scope. Keep raw
local spike scripts and outputs outside this roadmap change; only research conclusions belong
here.

#### Native parser promotion gates

The parser seam is implemented, but publication and broader installation remain evidence-gated:

- Publish raw goodput, errors, latency percentiles, CPU, and RSS with exact version and hardware
  context; Docker Desktop results remain directional rather than bare-metal evidence.
- Re-run Python, native, automatic, and fallback modes through the differential corpus,
  deterministic mutation tests, concurrent stress, and complete real-socket suite for every
  candidate release.
- Keep `dexpot-native` separately installable. Do not make it a default dependency or bundled
  installation until bare-metal Linux and cross-platform wheel gates show repeatable
  parser-heavy wins without unacceptable tail-latency, memory, overload, or lifecycle
  regressions.

The initial spike measured large parser-only gains and directional end-to-end improvements,
but those measurements are promotion evidence rather than README performance claims.

### 5. Production operations

Run operational work alongside endpoint features, preserving the synchronous programming model:

- Structured access and error logging with request IDs.
- Metrics for active connections, queue depth/age, saturation, worker restarts, response status,
  and drain duration; bounded telemetry that does not add a global hot-path lock.
- Explicit resource budgets for both GIL and FT deployments, including body buffering,
  accepted connections, and overload recovery.
- Configurable graceful-shutdown and per-connection deadlines.
- Trusted-proxy and forwarded-header policy.
- TLS guidance and explicit reverse-proxy deployment patterns.
- Health/readiness hooks that distinguish a live process from an accepting worker set.
- Stable configuration objects and environment-variable validation at startup.
- Linux and macOS multiprocess hardening; define an honest Windows strategy before claiming
  multiprocess support there.

### 6. Framework ecosystem

Once the contract and operations are stable:

- Progressive runnable examples under `examples/` for each supported use case.
- Keep bundled coding-agent skills synchronized with every stable route, request, response,
  concurrency, and deployment contract.
- Extension points with compatibility tests and a documented stability policy.
- Framework-level database/session lifecycle integrations that remain synchronous.
- Test clients and fixtures built on the real HTTP surface rather than a separate dispatcher.
- Deployment recipes and performance baselines for supported Python/runtime combinations.

## Non-goals

- Requiring `async def`, exposing an event loop API, or making ASGI the framework core.
- Becoming a thin wrapper around FastAPI, Starlette, Flask, or another server.
- Hiding GIL versus free-threaded behavior behind one misleading performance number.
- Treating unbounded work as a production strategy on either interpreter mode.
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

### Explicit annotation namespaces

Route decorators accept keyword-only `annotation_locals={"Alias": OriginalType}` for
factory/class annotation-only aliases and delayed registration. They never infer bindings
from caller locals. The mapping is shallow-copied at decorator creation; original closure
bindings override it. Module-global and concrete annotations need no extra option.
Unresolved parameter annotations fail at registration, including defaulted parameters;
explicit `body=` binding remains authoritative for its body parameter. Use only needed
bindings rather than retaining all factory locals. Wrapped handlers use their original
annotation scope. Test repeated factory calls and per-registration namespace isolation.
