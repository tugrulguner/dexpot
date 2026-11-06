# dexpot applications

dexpot is a synchronous Python API framework with an owned socket server. Handlers are plain
functions. Registration builds immutable `EndpointPlan` objects; serving freezes them into one
`ApplicationPlan` and `RouterPlan` before the listener opens. Traffic runs through real threads
selected for GIL or free-threaded CPython.

## When to use

- Build or change a dexpot HTTP application.
- Add typed path parameters or msgspec request/response structs.
- Configure GIL pools, overload limits, or multiprocess workers.
- Review a dexpot handler signature, shutdown path, or benchmark.
- Test behavior through the real HTTP server.

Do not introduce `async def`, an ASGI adapter, or a second dispatcher just for tests.

## Minimal application

```python
import msgspec

from dexpot import Dex, HttpLimits


class ItemIn(msgspec.Struct):
    name: str
    price: float


class ItemOut(msgspec.Struct):
    id: int
    name: str
    price: float


app = Dex(limits=HttpLimits(body_bytes=2 * 1024 * 1024))


@app.get("/items/{item_id}", response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    return ItemOut(id=item_id, name=f"item-{item_id}", price=9.99)


@app.post("/items", body=ItemIn, response=ItemOut)
def create_item(item: ItemIn) -> tuple[int, ItemOut]:
    return 201, ItemOut(id=1, name=item.name, price=item.price)
```

Serve it from the project directory:

```bash
dexpot serve main:app --host 127.0.0.1 --port 8000
```

The runtime package is `dexpot`; the command requires `dexpot[cli]`.

## Route rules

- Methods currently shipped: `get`, `post`, `put`, `patch`, and `delete`.
- Declare JSON bodies explicitly with `body=YourStruct`. Use msgspec `Struct`, not a
  Pydantic model.
- `response=T` strictly validates and projects output, including existing/nested Structs.
  Ordinary Struct schemas drop extra fields; `forbid_unknown_fields=True` rejects them.
  Invalid output returns a sanitized 500 before success bytes are sent.
- `response=None` is generic JSON encoding without validation or filtering. `Any` is not a
  privacy filter. Checked output rejects non-finite floats, including nested/optional/Any
  values and defaults. msgspec strict conversion semantics apply (integers may satisfy floats).
- Checked schemas support msgspec constraints, aliases, defaults, tagged unions, enums,
  bytes/base64, datetime and UUID strings. Custom types and schemas containing `__post_init__`
  or `__attrs_post_init__` hooks fail at registration. Invalid static Struct and dataclass defaults and known
  builtin factory defaults fail at registration, including omitted defaults. Application factories
  are not called at registration; their output is checked and projected before serialization,
  and cannot introduce Request context.
- `Response(body=None, status=200, headers=())` adds explicit JSON metadata.
  `RawResponse(body=b"", status=200, headers=(), content_type="application/octet-stream")`
  requires immutable bytes and `response=None`; it cannot bypass checked schemas.
  Envelopes are shallowly immutable. Headers are copied; pair sequences preserve duplicates.
- Status must be an integer (not bool), 200..599. Headers allow at most 64 pairs/16,384 encoded
  bytes, token names and Latin-1 values without controls. Content-Length, Transfer-Encoding,
  Connection, Keep-Alive, Upgrade, Trailer, TE, Server and Proxy-Connection remain server-owned.
  Content-Type is also reserved: use raw `content_type` (nonempty, at most 256 characters).
- `Response(status=204)` (also 205/304) permits an absent checked body. Other JSON bodies are
  validated before bodyless suppression. 204/304 omit Content-Length; 205 sends length zero.
  `RawResponse()` is an empty 200. Invalid envelopes inside handlers return sanitized 500.
- A handler may return a payload or `(status, payload)`. The declared response schema applies
  at every returned status, including errors. Use `response=None` for differently shaped bodies
  that do not share a supported schema.
- Path captures bind by parameter name, not by handler position.
- An `int` path annotation converts the capture and returns 422 when conversion fails.
- Path annotations support only `str`, `int`, unannotated parameters, and `Any`.
  `float`, `bool`, `Enum`, `Annotated`, unions, and explicit `None` are unsupported.
  In dexpot 0.8.1 and newer, unsupported path annotations raise `TypeError` during registration
  rather than silently receiving strings as in v0.8.0. To migrate an unsupported annotation,
  use `str` with explicit application validation or a typed JSON body where appropriate.
  Body/response schema support does not imply path conversion support.
- Path parameters may appear in any valid signature order because they bind by name.
- The first parameter remaining after path, Request and explicit source bindings is the body parameter. Put default-only parameters after it.
- Keyword-only parameters, callable objects, classes, and `functools.partial` work. Class
  annotation namespaces follow the effective metaclass `__call__` or MRO-selected constructor
  (`__new__` before `__init__` on the same class), including `functools.partialmethod`
  constructors. Explicit class `__signature__` aliases need
  concrete annotations or `annotation_locals`; do not guess a constructor namespace.
  The effective call
  must remain synchronous; coroutine functions, async generators, and detectable wrapped
  asynchronous callables are rejected at registration.
- Signatures that cannot be inspected and handlers using `*args` or `**kwargs` are rejected at
  registration.
- Every path capture must have a matching handler parameter.
- Two routes with one method and the same structural shape conflict: `/users/{id}` and
  `/users/{name}` cannot coexist.
- Late route registration fails after application compilation. Declare every route before
  calling `serve()`; do not mutate the application while traffic is running.

### Typed input sources (unreleased)

Unreleased: typed query/header/cookie inputs. Public v0.8.1 does not include these markers.
Use source containing the feature, not the published 0.8.1 package. Declare explicit aliases
with `Annotated[int, Query("limit")]`, `Annotated[str, Header("x-request-id")]`, or
`Annotated[str, Cookie("theme")]`. Base types are exact str/int/finite float/bool; booleans
accept only true/false in ASCII case-insensitive form. Defaults must have the exact declared
type; missing selects a valid default, while empty/invalid present values do not.

Required missing, repeated requested query/cookie names, invalid conversions and selected-value
UTF-8 errors return 422 before the handler. New errors contain only source/declared alias/fixed
reason, never supplied values. Header names are case-insensitive and values already normalized;
repeated physical headers are comma-folded, not independently recoverable. Query names/values
decode UTF-8 and plus-as-space only on marked routes; unknown values are ignored, but malformed
name encodings fail lookup. `%GG` still fails at the HTTP parser with 400 on every route.
Cookies use strict ASCII cookie pairs, optional balanced quotes, no URL decoding, and reject
malformed headers when needed. Do not treat a header's presence as authentication.

Raw Request query/header views and the existing path/body rules remain separate. No DI,
OpenAPI, lists/Optional/Enum/extra Annotated metadata, new path conversions or proxy trust are
provided by this feature. Follow the full route contract for cookie framing and error ordering.

Inject parsed request context by annotating a parameter with `Request`; the parameter name and
position are unrestricted:

```python
from dexpot import Request


@app.post("/items/{item_id}", body=ItemIn)
def update(item: ItemIn, item_id: int, *, request: Request) -> dict[str, object]:
    return {
        "item_id": request.params["item_id"],
        "query": request.query,
        "same_body": request.body is item,
    }
```

The frozen, GC-tracked object exposes `method`, `path`, raw string `params`, the raw `query`
string, lowercase-name `headers`, received `raw_body` bytes, and the validated `body`. Handlers
without a `Request` annotation do not allocate the public context object. Freezing is shallow:
contained dictionaries and body values remain request-local application objects. Dexpot always
rejects a directly returned Request. On Request-aware and checked routes, it also rejects nested Request values in supported
response containers. Explicit extraction of sensitive fields and nested, manually
created Request values returned by unchecked requestless handlers are outside the recursive guard.

Prefer errors at registration. If a declaration can be proven invalid while the module is
imported, do not defer it until a request.

### Opt-in OpenAPI export (unreleased)

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
Postponed schema field annotations containing calls are excluded for Struct, dataclass, attrs,
TypedDict and NamedTuple owners, including NewType wrappers, because re-evaluation can
disagree with an existing decoder. Construct constrained aliases eagerly (for example,
`Name = Annotated[str, msgspec.Meta(min_length=1)]`) and use `name: Name` in the Struct.
References must be statically resolvable: inherited class aliases and literal lookups in
built-in dictionaries/lists/tuples are supported. Opaque attribute getters/descriptors, custom subscriptions or
union operators, conditional type expressions and unresolved references reject rather than
silently skipping a schema. Literal payloads and literal Annotated metadata remain values.
Model annotations, referenced aliases, defaults and schema metadata must stay unchanged
from their first native/msgspec use. Captured models have weak, identity-based process-wide
fingerprints: later conflicting captures reject across routes and applications, while existing
snapshots remain intact. Declare a new model type for a new contract. The exporter cannot
reconstruct bindings from an external native cache created before its first capture; changing
a model in that unobserved interval is unsupported.

### Explicit annotation namespaces

Route decorators accept keyword-only `annotation_locals={"Alias": OriginalType}` for
factory/class annotation-only aliases and delayed registration. They never infer bindings
from caller locals. The mapping is shallow-copied at decorator creation; original closure
bindings override it. Module-global and concrete annotations need no extra option.
Unresolved parameter annotations fail at registration, including defaulted parameters;
explicit `body=` binding remains authoritative for its body parameter. Use only needed
bindings rather than retaining all factory locals. Wrapped handlers use their original
annotation scope. Annotations resolve afresh per registration, and `body=`/`response=` are
route-local rather than stored on shared handler functions. Test repeated factory calls,
handler reuse across applications, and per-registration namespace isolation.

### Protocol and configuration policy

Once a request reaches parsing, HEAD responses never include body bytes, including parser and
handler errors; admission can reject an unread connection before its method is known. Automatic
GET-to-HEAD routing is not provided. Requests with an `Expect` header are rejected with 417 and connection close
before reading their body. Retry without `Expect` when appropriate.

`DEXPOT_POOL=0` retains automatic sizing. Negative pool sizes and nonpositive
`DEXPOT_MAX_QUEUE` or `DEXPOT_MAX_CONNECTIONS` values fail at import, before a listener can
open; zero queue or connection capacity is not a supported no-wait mode. These validation
rules apply in both interpreter modes.

## HTTP boundary

- `HttpLimits` is the one immutable policy for request-line bytes, total header bytes, header
  count, body bytes, idle-read seconds, and absolute head/body deadlines. Keep transport
  policy out of route decorators.
- HTTP/1.1 keeps valid connections alive by default; HTTP/1.0 closes by default unless the
  client requests keep-alive.
- Dexpot rejects ambiguous `Content-Length`, transfer encodings, malformed targets, invalid
  path escapes, oversized input, and idle partial requests with stable errors and closes.
- Paths are UTF-8 percent-decoded. Duplicate slashes and trailing slashes are distinct rather
  than normalized. A known path with the wrong method returns 405 and `Allow`.
- Request targets are currently origin-form only (`/path?query`); absolute-form proxy targets
  are rejected in the current alpha boundary.
- Unexpected handler exceptions are logged server-side and return only
  `{"detail":"internal server error"}` to the client.
- The pure-Python request-head parser is the semantic reference and fallback. Backend selection
  defaults to `auto`: use a compatible separately installed `dexpot-native` extension when
  present, otherwise Python. `DEXPOT_HTTP_PARSER=python` forces the reference parser and
  `native` requires the extension. Native code does not own sockets, bodies, handlers,
  scheduling, or supervision.

## Execution model

Free-threaded builds use the bounded connection-owner policy only when the GIL is actually disabled; a free-threaded build with the GIL enabled uses the GIL scheduler. The scheduler is bound once when `serve()` starts, after application imports, from the actual GIL state. A free-threaded build can have its GIL enabled by a native extension loaded during application setup:

- **GIL disabled on free-threaded Python:** one process, one owning thread per admitted connection. Threads
  can execute Python in parallel. `DEXPOT_MAX_CONNECTIONS` defaults to 1,024; excess
  connections receive 503 before a thread is created.
- **GIL build:** a bounded pool owns connections. The queue is bounded; saturated admission
  returns 503 rather than accumulating unlimited work.
- **GIL + `DEXPOT_WORKERS>1`:** POSIX-only `SO_REUSEPORT` processes, each with a local pool
  and listener. Unsupported platforms raise instead of silently changing behavior.

Tune before importing the application:

```bash
DEXPOT_MAX_CONNECTIONS=512 dexpot serve main:app
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app
DEXPOT_WORKERS=4 dexpot serve main:app
```

A worker owns a keep-alive connection until close. Never requeue an idle live connection:
it consumes admission capacity and can block a worker waiting for the next request.

SIGINT/SIGTERM stop new admission and allow active connections up to five seconds to drain.
Multiprocess workers restart after crashes.

## Current boundaries

Do not claim these as shipped:

- Automatic OpenAPI documentation UI or security inference, middleware, dependency injection, authentication, streaming, WebSockets, or TLS.
- Chunked request bodies; transfer encodings are deliberately rejected.
- Query/header injection into handler parameters.
- Cross-platform multiprocess serving.

Structured request IDs, access logs, metrics, trusted-proxy policy, and deployment TLS guidance
remain production-operations work. Do not describe parser hardening alone as production readiness.

## Testing

Behavior tests use the real socket server and an HTTP client. For a new endpoint feature,
cover at least:

1. one successful request;
2. malformed or invalid input;
3. registration-time rejection for invalid declarations; and
4. keep-alive behavior when connection ownership could change.

When an application depends on its concurrency configuration, test the documented pool,
queue, and worker settings through real requests on every supported runtime it claims. Record
the Python version plus `getattr(sys, "_is_gil_enabled", lambda: True)()` as evidence; the
compatible probe reports the GIL as enabled on Python versions that do not expose the helper.
Verify successful responses and expected 503 overload behavior where applicable.

## Benchmarking

Use `wrk`, not a Python load generator. Compare equivalent routes, validation, status codes,
and response bodies. Report successful responses, errors, p50/p95/p99 latency, CPU/memory,
Python version, `sys._is_gil_enabled()`, pool size, queue size, and process count.

A fast 503 is overload protection, not successful application throughput. Never use total
RPS alone when one server is shedding requests.

## Verification

Before calling a dexpot application change complete:

- the application imports and all routes register;
- real HTTP success and failure paths pass; and
- scheduler or concurrency claims include the Python version and
  `getattr(sys, "_is_gil_enabled", lambda: True)()` evidence.


## Application lifecycle

Runnable example inventory: `minimal.py`, `typed_crud.py`, `bounded_api.py`, `response_policy.py`, and `lifecycle.py` (run from the repository with `uv run python examples/<name>.py`).

Requires dexpot 0.8.0 or newer. Register process-scoped synchronous resource managers with `app.lifespan(factory)`. Factories
are not called during registration or compilation; each serving process enters them before
accepting traffic and exits in reverse order. GIL worker processes acquire independently;
free-threaded connection threads share the process-local resources, which must be thread-safe.
Partial startup unwinds resources already entered. Shutdown has a bounded drain and Python
handler threads cannot safely be forcibly cancelled. When a handler outlives that deadline,
resources remain acquired until the last handler finishes; deferred cleanup runs on a temporary
lifecycle finalizer thread, not a connection owner or necessarily the acquisition thread. Deferred
cleanup errors are logged while every registered exit is attempted. Managers requiring enter/exit thread affinity
are unsupported. Forced process termination may skip Python cleanup.
