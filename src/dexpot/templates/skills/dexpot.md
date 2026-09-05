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
- `response=YourStruct` selects a precompiled encoder. It does **not** currently validate
  the handler return type, so return the declared type yourself.
- A handler may return a payload or `(status, payload)`.
- Path captures bind by parameter name, not by handler position.
- An `int` path annotation converts the capture and returns 422 when conversion fails.
- Path parameters may appear in any valid signature order because they bind by name.
- The first non-path parameter is the body parameter. Put default-only parameters after it.
- Keyword-only parameters work. `*args` and `**kwargs` are rejected at registration.
- Every path capture must have a matching handler parameter.
- Two routes with one method and the same structural shape conflict: `/users/{id}` and
  `/users/{name}` cannot coexist.
- Late route registration fails after application compilation. Declare every route before
  calling `serve()`; do not mutate the application while traffic is running.

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
contained dictionaries and body values remain request-local application objects. Do not return
the context; Dexpot rejects it rather than serializing request headers and body data.

Prefer errors at registration. If a declaration can be proven invalid while the module is
imported, do not defer it until a request.

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

The scheduler is selected when dexpot imports:

- **Free-threaded build:** one process, one owning thread per accepted connection. Threads
  can execute Python in parallel.
- **GIL build:** a bounded pool owns connections. The queue is bounded; saturated admission
  returns 503 rather than accumulating unlimited work.
- **GIL + `DEXPOT_WORKERS>1`:** POSIX-only `SO_REUSEPORT` processes, each with a local pool
  and listener. Unsupported platforms raise instead of silently changing behavior.

Tune before importing the application:

```bash
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app
DEXPOT_WORKERS=4 dexpot serve main:app
```

A worker owns a keep-alive connection until close. Never requeue an idle live connection:
it consumes admission capacity and can block a worker waiting for the next request.

SIGINT/SIGTERM stop new admission and allow active connections up to five seconds to drain.
Multiprocess workers restart after crashes.

## Current boundaries

Do not claim these as shipped:

- OpenAPI, middleware, dependency injection, authentication, streaming, WebSockets, or TLS.
- Chunked request bodies; transfer encodings are deliberately rejected.
- Query/header injection into handler parameters.
- Runtime enforcement of `response=` types.
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

### Explicit annotation namespaces

Route decorators accept keyword-only `annotation_locals={"Alias": OriginalType}` for
factory/class annotation-only aliases and delayed registration. They never infer bindings
from caller locals. The mapping is shallow-copied at decorator creation; original closure
bindings override it. Module-global and concrete annotations need no extra option.
Unresolved parameter annotations fail at registration, including defaulted parameters;
explicit `body=` binding remains authoritative for its body parameter. Use only needed
bindings rather than retaining all factory locals. Wrapped handlers use their original
annotation scope. Test repeated factory calls and per-registration namespace isolation.
