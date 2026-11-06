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
```

Set `DEXPOT_EXAMPLE_PORT` when port 8000 is already in use. Run one server at a time.
The latest lifecycle and nested-response walkthroughs below target dexpot 0.8.0 or newer;
none requires a database, credentials, or network service beyond the local HTTP server.

## Capability map

| Example | What it exercises |
| --- | --- |
| `minimal.py` | Synchronous handler, integer path binding, typed JSON response |
| `typed_crud.py` | JSON body validation, GET/POST/PUT/DELETE, checked creation, explicit generic errors, raw Request metadata, thread-safe process-local state |
| `bounded_api.py` | Configured HTTP limits, 413/422/405 errors, explicit annotation namespaces |
| `response_policy.py` | Public-field projection, custom and duplicate headers, sanitized output failures, raw bytes, bodyless 204, status tuples |
| `nested_responses.py` | Nested Struct projection, malformed/non-finite nested output rejection, valid recovery after failure |
| `lifecycle.py` | Serving-time acquisition, explicit resource access, reverse cleanup, partial-startup rollback |
| `typed_inputs.py` | Unreleased explicit scalar Query/Header/Cookie sources, pagination/filtering, defaults, strict failures and raw Request compatibility |
| `openapi.py` | Unreleased opt-in OpenAPI snapshots, explicit JSON document serving/file export, checked 201 responses and input validation |

`typed_inputs.py` and `openapi.py` require source containing their unreleased features; the
other examples exercise shipped contracts. No example introduces dependency injection or
the experimental socket-I/O redesign. Public Request query/header metadata stays
raw; application state is not shared across GIL worker processes.

## Typed scalar inputs (unreleased)

Unreleased: typed query/header/cookie inputs. Public v0.8.1 does not include these markers.
`typed_inputs.py` uses `Annotated` with explicit `Query`, `Header` and `Cookie` aliases and exact
str/int/finite float/bool types. It does not add path converters or authentication.

```bash
uv run python examples/typed_inputs.py
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&min_price=3&include_archived=false' \
  -H 'X-Request-ID: example-1' -H 'Cookie: theme=dark'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=' -H 'X-Request-ID: example-2'
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&%6cimit=2' -H 'X-Request-ID: example-3'
curl -i 'http://127.0.0.1:8000/raw?value=%FF'
```

The first call filters and paginates fixture items. Empty numeric input and duplicate decoded
requested keys return 422 before the handler; defaults apply only when absent. Booleans accept
only true/false, case-insensitive. The raw Request route deliberately returns the original query
text without enabling UTF-8 query-value decoding. Headers are normalized/case-insensitive;
physical duplicates have already been comma-folded. Cookie parsing uses strict ASCII pairs,
optional balanced quotes and no URL decoding; requested duplicate cookies fail. Unknown
well-formed values are ignored. See the route reference for framing and error ordering.

## OpenAPI snapshot example (unreleased)

Unreleased: OpenAPI export. Public v0.8.1 does not include Dex.openapi().
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
Postponed schema field annotations containing calls are excluded for Struct, dataclass,
TypedDict and NamedTuple owners, including NewType wrappers, because re-evaluation can
disagree with an existing decoder. Construct constrained aliases eagerly (for example,
`Name = Annotated[str, msgspec.Meta(min_length=1)]`) and use `name: Name` in the Struct.

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
