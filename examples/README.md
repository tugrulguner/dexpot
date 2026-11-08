# Runnable examples

These examples form a small progression over dexpot's shipped public surface. Run each file
from the repository root after `uv sync --all-extras`:

```bash
uv run python examples/minimal.py
uv run python examples/typed_crud.py
uv run python examples/bounded_api.py
uv run python examples/response_policy.py
uv run python examples/nested_responses.py
uv run python examples/typed_inputs.py
uv run python examples/openapi.py
uv run python examples/lifecycle.py
uv run python examples/database.py
```

Set `DEXPOT_EXAMPLE_PORT` when port 8000 is already in use. Run one server at a time.
The latest lifecycle and nested-response walkthroughs below target dexpot 0.8.0 or newer;
`database.py` uses a local SQLite file through the Python standard library; none requires
credentials or an external database/network service.

## Capability map

| Example | What it exercises |
| --- | --- |
| `minimal.py` | Synchronous handler, integer path binding, typed JSON response |
| `typed_crud.py` | JSON body validation, GET/POST/PUT/DELETE, checked creation, explicit generic errors, raw Request metadata, thread-safe process-local state |
| `bounded_api.py` | Configured HTTP limits, 413/422/405 errors, explicit annotation namespaces |
| `response_policy.py` | Public-field projection, custom and duplicate headers, sanitized output failures, raw bytes, bodyless 204, status tuples |
| `nested_responses.py` | Nested Struct projection, malformed/non-finite nested output rejection, valid recovery after failure |
| `lifecycle.py` | Serving-time acquisition, explicit resource access, reverse cleanup, partial-startup rollback |
| `database.py` | Bounded process-local SQLite connections, exclusive handler leases, durable writes, rollback and the post-commit encoding boundary |
| `typed_inputs.py` | Explicit scalar Query/Header/Cookie sources, pagination/filtering, defaults, strict failures and raw Request compatibility |
| `openapi.py` | Opt-in OpenAPI snapshots, explicit JSON document serving/file export, checked 201 responses and input validation |

`typed_inputs.py` and `openapi.py` require dexpot 0.9.0 or newer; the other examples
target the versions stated below. No example introduces dependency injection or
the experimental socket-I/O redesign. Public Request query/header metadata stays
raw; application state is not shared across GIL worker processes.

## Database resources and transactions

`database.py` builds on the existing `app.lifespan(factory)` API (dexpot 0.8.0 or newer),
not request-scoped dependency injection. Its SQLite pool is acquired at serving startup,
not module import. A handler obtains an exclusive connection lease with an ordinary
context manager and returns it on both successful and exceptional exits. Pool exhaustion
returns 503 rather than waiting indefinitely. This is a teaching example, not a production
pool implementation or an authentication service.

Process/application resources are distinct from request leases. Connection threads within
one process share the pool; GIL worker processes have independent pools. Budget aggregate
connections across every process, and follow the database driver's thread-affinity rules.
This example uses one serving process and SQLite connections configured for exclusive use
across request threads. A keep-alive HTTP connection does not own a database lease between
requests. Normal lifecycle cleanup waits for active handlers; forced process termination
cannot guarantee Python cleanup.

Validation rejects malformed typed bodies before a handler can acquire a lease. An exception
inside a write transaction rolls back. However, an encoding failure after commit returns 500
without undoing the committed write: response preparation happens after the handler returns.
Socket failure after commit cannot undo the transaction either. Do not infer database/HTTP
atomicity or retry safety from the response status; design idempotency separately.

```bash
DEXPOT_EXAMPLE_DB=./items.sqlite3 DEXPOT_EXAMPLE_POOL_SIZE=2 uv run python examples/database.py
# In another terminal (GET uses the id returned by the first POST):
curl -i -X POST http://127.0.0.1:8000/items -H 'Content-Type: application/json' \
  -d '{"name":"keyboard","price":19.5}'
curl -i http://127.0.0.1:8000/items/1
curl -i -X POST http://127.0.0.1:8000/rollback -H 'Content-Type: application/json' \
  -d '{"name":"discard","price":1.0}'
curl -i -X POST http://127.0.0.1:8000/encoding-failure -H 'Content-Type: application/json' \
  -d '{"name":"committed","price":3.0}'
```

The POST statuses are 201, 409 and 500 respectively. The rollback row is absent; the
encoding-failure row is present despite 500. Stop and restart against the same file to
verify persistence. Malformed typed input returns 422 before acquiring a lease. Set
`DEXPOT_EXAMPLE_EVENTS=./database-events.jsonl` to observe open/acquire/commit/rollback/
release/close events. `DEXPOT_EXAMPLE_DB` must name a non-empty on-disk file: empty paths and `:memory:`
are rejected before opening connections because they create private per-connection stores.
Item IDs outside SQLite's signed 64-bit range return 404 before acquiring a lease.
Both representable bounds remain ordinary lookups; this is local to the database example,
not a restriction on dexpot's integer path converter.
Pool size defaults to 4; SQLite lock contention has a 250 ms busy
timeout and may produce a sanitized 500 rather than an automatic retry. Pool exhaustion
is a separate immediate 503. `/hold` intentionally holds a lease briefly for local
exhaustion demonstrations; it is not query-configurable or a production endpoint.

Run the example only in a local demonstration environment. Its deliberate rollback and
invalid-response endpoints teach these boundaries rather than hiding them. It needs no
Query/Header/Cookie markers, OpenAPI export, hooks or new framework runtime behavior.

## Retry after a committed write

This source-checkout addition extends `database.py` using existing framework APIs; it is
application-owned recovery, not built-in framework retry handling. Start the server above,
then run this bounded client in another terminal with the same host/port settings:

```bash
uv run python examples/database.py --retry-demo
```

The client generates an `operation_id` once, then sends at most two identical requests to
`POST /retry-safe/items`. Its local-only `X-Demo-Fail-Reply: 1` header deliberately breaks
the first reply **after commit**. The first request returns 500, but the retry returns the
original 201 result and item ID instead of inserting again. The client reads that item back
and prints JSON with `first_status`, `retry_status`, `operation_id` and `item`.

To inspect the same boundary manually, use a fresh operation ID for a new logical write,
and reuse that exact ID and payload on every retry:

```bash
curl -i -X POST http://127.0.0.1:8000/retry-safe/items \
  -H 'Content-Type: application/json' -H 'X-Demo-Fail-Reply: 1' \
  -d '{"operation_id":"example-create-1","name":"tea","price":2.5}'
curl -i -X POST http://127.0.0.1:8000/retry-safe/items \
  -H 'Content-Type: application/json' -H 'X-Demo-Fail-Reply: 1' \
  -d '{"operation_id":"example-create-1","name":"tea","price":2.5}'
```

The item and operation record commit in the same database transaction. The same operation ID
and same validated payload replay the original result, including after a server restart
against the same SQLite file. Reusing that ID with different data returns 409 without
another write. A new ID means a new operation, even if its name and price match an older one.
A single transaction also prevents simultaneous retries from each inserting a record.
The ordinary `/items` and deliberately unsafe `/encoding-failure` routes remain unchanged;
blind retries there can still create duplicates.

These are local demonstration endpoints, not authenticated production services. Operation
IDs are not credentials. Retain the operation records for as long as retries must be safe;
the table grows with successful unique operations, so a production retention policy must
match the promised retry window. Deleting records or resetting the database removes that
protection. Retry-route writers wait at most 250 ms for their process-local write gate;
a busy gate returns 503 before acquiring a connection. Pool exhaustion and SQLite lock
timeouts remain bounded failures, not automatic server retries. This does not promise
atomic database/HTTP delivery or universal exactly-once execution.

## Typed scalar inputs

Included in v0.9.0: typed query/header/cookie inputs.
`typed_inputs.py` uses `Annotated` with explicit `Query`, `Header` and `Cookie` aliases and exact
str/int/finite float/bool types. It does not add path converters or authentication.

```bash
uv run python examples/typed_inputs.py
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&min_price=3&include_archived=false' \
  -H 'X-Request-ID: example-1' -H 'Cookie: theme=dark'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=' -H 'X-Request-ID: example-2'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&limit=2' -H 'X-Request-ID: repeated'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&limit=1' -H 'X-Request-ID: identical'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&%6cimit=2' -H 'X-Request-ID: example-3'
curl -i 'http://127.0.0.1:8000/raw?value=%FF'
```

The first call filters and paginates fixture items. Empty numeric input and duplicate decoded
requested keys return 422 before the handler; defaults apply only when absent.
Both `limit=1&limit=2` and `limit=1&limit=1` return
`{"detail":"query parameter 'limit': repeated"}`. A declared scalar accepts only one
occurrence, even when repeated values match: there is no first-value or last-value rule.
Names are matched after decoding, so `%6cimit` also counts as `limit`. Booleans accept
only true/false, case-insensitive. The raw Request route deliberately returns the original query
text without enabling UTF-8 query-value decoding. Headers are normalized/case-insensitive;
physical duplicates have already been comma-folded. Cookie parsing uses strict ASCII pairs,
optional balanced quotes and no URL decoding; requested duplicate cookies fail. Unknown
well-formed values are ignored. See the route reference for framing and error ordering.

## OpenAPI snapshot example

Included in v0.9.0: OpenAPI export.
Create `Dex(openapi=True)` before declaring routes to capture OpenAPI 3.1 metadata at
registration. `app.openapi(title="Example API", version="development")` returns a detached
JSON-compatible document and freezes further registration after successful export. API
`info.version` is caller metadata, not the package version. Ordinary applications do not
load the exporter or capture schemas.

The export uses existing endpoint bindings and msgspec wire schemas, not fresh handler
introspection. It describes path/query/header/cookie aliases, required values, scalar defaults,
JSON bodies and declared response schemas. Runtime-selected statuses are not guessed: checked
responses include the declared payload or a detail error envelope; unchecked/raw response media
and shapes remain unspecified. Statuses 204/205/304 have no content. Query lexical rules,
normalized headers and strict cookies still govern requests; JSON Schema does not implement
those transport parsers.

There is no automatic endpoint, documentation UI, authentication/security inference or DI.
The caller chooses whether to save or serve the document. Exported defaults and docstrings are
public metadata: review them before serving the document. Unsupported schema/component names,
external/unresolved references, ignored OpenAPI headers (Accept, Content-Type, Authorization),
and contradictory templated paths fail instead of producing a misleading document.
Postponed schema field annotations containing calls are excluded for Struct, dataclass, attrs,
TypedDict and NamedTuple owners, including NewType wrappers, because re-evaluation can
disagree with an existing decoder. Construct constrained aliases eagerly (for example,
`Name = Annotated[str, msgspec.Meta(min_length=1)]`) and use `name: Name` in the Struct.
References must be statically resolvable: inherited class aliases and literal lookups in
built-in dictionaries/lists/tuples are supported. Opaque attribute getters/descriptors, custom subscriptions or
union operators, conditional type expressions and unresolved references reject rather than
silently skipping a schema. Literal payloads and literal Annotated metadata remain values.
Postponed model annotations follow native module-before-class lookup, including
PEP 695 type parameters; class-local aliases remain fallbacks when unshadowed.
Generic-model availability still follows native interpreter/msgspec support.
Opaque module namespace getters, including replacement `__dict__` descriptors,
are rejected before the exporter reads their namespace.
Model metaclasses may not replace structural metadata readers (such as `__dict__`
or `__annotations__`) or native field/default metadata with opaque descriptors;
ordinary/native descriptors remain supported.
Custom fallback attribute getters cannot fabricate schema metadata; standard enum
attribute lookup remains supported.
Model annotations, referenced aliases, defaults and schema metadata must stay unchanged
from their first native/msgspec use. Captured models have weak, identity-based process-wide
fingerprints: later conflicting captures reject across routes and applications, while existing
snapshots remain intact. Declare a new model type for a new contract. The exporter cannot
reconstruct bindings from an external native cache created before its first capture; changing
a model in that unobserved interval is unsupported.

```bash
uv run python examples/openapi.py
curl -s http://127.0.0.1:8000/openapi.json
curl -i -X POST 'http://127.0.0.1:8000/items/7?limit=2' \
  -H 'Content-Type: application/json' -H 'X-Request-ID: example' \
  -d '{"name":"tea","price":3.5}'
```

The source example explicitly serves a precomputed document alongside a checked 201 response,
body/path/query/header/cookie bindings and a validation failure. `--export openapi.json` writes
the document without starting a server; an existing file is not overwritten.

## `minimal.py`

The smallest application: a typed integer path capture and a msgspec response.

```bash
curl -s http://127.0.0.1:8000/items/7
```

Expected response:

```json
{"id":7,"name":"item-7","price":7.0}
```

## `typed_crud.py`

A thread-safe in-memory CRUD service showing typed JSON request bodies, compiled response
encoders, status/payload returns, and application state shared by connection threads.

```bash
curl -s http://127.0.0.1:8000/items/1
curl -s -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"keyboard","price":79.0}'
curl -s -X PUT http://127.0.0.1:8000/items/2 \
  -H 'Content-Type: application/json' \
  -d '{"name":"keyboard-pro","price":99.0}'
curl -s -X DELETE http://127.0.0.1:8000/items/2
```

The lock is application code, not framework machinery. It keeps the mutable dictionary safe
when handlers execute concurrently.

## `bounded_api.py`

Customizes `HttpLimits` and demonstrates the fail-closed HTTP boundary. The `/context`
route also demonstrates typed Request injection with an explicit factory-local
`annotation_locals` binding.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/context  # {"method":"GET"}
curl -s -X POST http://127.0.0.1:8000/echo \
  -H 'Content-Type: application/json' \
  -d '{"text":"hello"}'
```

The example deliberately caps bodies at 64 bytes. Oversized requests receive 413, malformed
JSON receives 422, and calling `POST /health` receives 405 with `Allow: GET`.

## Path annotation boundary

Path annotations support only `str`, `int`, unannotated parameters, and `Any`.
`float`, `bool`, `Enum`, `Annotated`, unions, and explicit `None` are unsupported.
In dexpot 0.8.1 and newer, unsupported path annotations raise `TypeError` during registration
instead of silently passing strings in v0.8.0. The integer route in `minimal.py` converts
`/items/7` to an integer and rejects `/items/not-an-int` with 422. Raw string captures need
explicit application validation before numeric comparisons or boolean decisions; the string
`"false"` is truthy in Python. JSON body and response schemas support their own richer types.

## Execution modes

The application code does not change between interpreters:

```bash
# Tune bounded GIL threads and admission queue.
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 uv run python examples/typed_crud.py

# Fan out across process-local SO_REUSEPORT listeners on supported POSIX GIL builds.
DEXPOT_WORKERS=4 uv run python examples/typed_crud.py

# Tune the free-threaded active-connection cap (default: 1024).
DEXPOT_MAX_CONNECTIONS=512 uv run python examples/typed_crud.py

# When sys._is_gil_enabled() is false, capped connection-owning threads can
# execute Python in parallel. A free-threaded build with its GIL enabled still
# selects the bounded GIL serving model.
```

Dexpot is still alpha software. These examples validate the current framework contract; they
are not production deployment recipes. See the root README and roadmap for current boundaries.

## Checked response policy

Run `uv run python examples/response_policy.py` and request `/public` for projected JSON
with duplicate Set-Cookie headers, `/invalid` for a sanitized output-validation 500, `/raw`
for plain bytes, `/empty` for a bodyless 204, and `/tuple` for the existing status/payload API.
The `/invalid` route deliberately logs a server-side validation error. Checked schemas reject
non-finite floats and post-init hooks; raw responses require an unchecked route.

In `typed_crud.py`, GET and PUT explicitly use `response=None` because their success and
404 bodies have different shapes. POST still checks `response=Item`. A declared response schema
applies to returned payloads at every status, including tuple and Response error bodies.


## Nested checked responses (0.8.0+)

Run `uv run python examples/nested_responses.py`, then:

```bash
curl -i http://127.0.0.1:8000/catalog
# {"items":[{"name":"tea","quantity":1,"price":2.5}],"note":"ready"}
curl -i http://127.0.0.1:8000/invalid
curl -i http://127.0.0.1:8000/nonfinite
# Both return 500 {"detail":"internal server error"} and log validation failures.
```

`/catalog` projects a private catalog and its nested private item into public Struct
schemas, omitting both internal catalog metadata and the item's supplier secret.
The public schema supplies defaults when fields are absent. `/invalid` supplies
an incorrectly typed nested field; `/nonfinite` puts NaN in a float field, so the
failure exercises finite-number validation rather than an integer type mismatch.
A subsequent valid request still succeeds on the same keep-alive connection.

The supported nested Struct response preparation introduced in 0.8.0 preserves
validation and projection. This example asserts the public contract, not a
throughput improvement or a free-threaded optimization.

## Paired application lifecycle

Requires dexpot 0.8.0 or newer. The yielded context-manager value is not automatically injected into handlers.

Register synchronous context-manager factories with `app.lifespan(factory)`. Registration and
plan compilation do not call the factory. Each serving process enters factories in order before
accepting traffic and normally exit them in reverse order after active handlers finish. Shutdown waits
for a bounded drain deadline; if handlers remain, cleanup is deferred until they finish. A factory
that fails to enter aborts startup and already-entered managers are unwound. Forced process
termination may skip Python cleanup. These resources are
process-owned: GIL worker processes each acquire their own copy; free-threaded serving threads
share the serving process's acquired resources, so those resources must be thread-safe.

Run `uv run python examples/lifecycle.py`, then:

```bash
curl -i http://127.0.0.1:8000/health
curl -i -X PUT http://127.0.0.1:8000/cache/tea \
  -H 'Content-Type: application/json' -d '{"value":"oolong"}'
curl -i http://127.0.0.1:8000/cache/tea
# {"key":"tea","value":"oolong"}
curl -i -X PUT http://127.0.0.1:8000/cache/tea \
  -H 'Content-Type: application/json' -d '{"value":7}'
# 422; the previously stored value is unchanged.
```

The cache is constructed inside its context-manager factory, then published through
an explicit process-local reference for handlers. Its lock protects reads, writes,
and clearing across free-threaded serving threads. Missing keys return 404.
A later startup check models dependency readiness; if it fails, the acquired cache
is closed without starting the listener. The example does not use yielded-value
injection, durable storage, or cross-process state sharing. With the default single
GIL serving process, writes are visible to subsequent requests; configuring multiple
GIL workers would give each worker an independent cache.

To observe acquisition and cleanup, or demonstrate rollback before traffic:

```bash
DEXPOT_EXAMPLE_EVENTS=./lifecycle-events.jsonl uv run python examples/lifecycle.py
# Stop normally with Ctrl-C; the cache is cleared after the startup check exits.
DEXPOT_EXAMPLE_EVENTS=./rollback-events.jsonl DEXPOT_EXAMPLE_FAIL_STARTUP=check \
  uv run python examples/lifecycle.py
# Exits nonzero. Events: acquire:cache, enter:check, exit:check, release:cache.
```

Event paths are opt-in JSONL files (one event per line, with process IDs); the example
has no import-time resource acquisition. Event-file I/O errors log a warning without
preventing cache cleanup or hiding a startup error. The files are append-only, so use a fresh
path when comparing one run's events. Startup errors and output-validation errors
are intentional in these failure demonstrations, not a successful server launch.

A disconnected client does not cancel Python handler work. Shutdown drains for a bounded period; if
handlers remain, their connections and application resources are left untouched and cleanup runs
when the last handler finishes. In a single-process embedded caller, serve returns after the deadline
without killing the host interpreter; resources remain owned until quiescence. Forced process
termination may skip Python cleanup.
