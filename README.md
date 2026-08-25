# dexpot

<p align="center">
  <strong>Plain handlers. Real threads. Free-threaded Python.</strong>
</p>

<p align="center">
  A synchronous Python API framework that compiles routes once, validates JSON with msgspec,
  and adapts its concurrency model to the interpreter running it.
</p>

<p align="center">
  <a href="https://github.com/tugrulguner/dexpot/actions/workflows/ci.yml"><img src="https://github.com/tugrulguner/dexpot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/dexpot/"><img src="https://img.shields.io/pypi/v/dexpot" alt="PyPI version"></a>
  <a href="https://pypi.org/project/dexpot/"><img src="https://img.shields.io/pypi/pyversions/dexpot" alt="Python versions"></a>
  <a href="https://github.com/tugrulguner/dexpot/stargazers"><img src="https://img.shields.io/github/stars/tugrulguner/dexpot?style=flat" alt="GitHub stars"></a>
  <a href="https://github.com/tugrulguner/dexpot/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-dexpot">Why dexpot</a> ·
  <a href="#execution-model">Execution model</a> ·
  <a href="#current-boundaries">Boundaries</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#contributing">Contributing</a>
</p>

## Why dexpot

Most Python API frameworks were designed around a permanent GIL: async I/O in one process,
or several worker processes for CPU parallelism. Free-threaded CPython changes that tradeoff.
Threads can execute Python simultaneously and share normal in-process state.

dexpot is designed around that runtime instead of hiding it behind an ASGI adapter:

- **Plain synchronous handlers.** No `async def`, event loop, or coroutine bridge.
- **Compiled endpoint plans.** Route matching metadata, argument sources, path conversions,
  and msgspec codecs are prepared when a handler is registered.
- **Interpreter-adaptive scheduling.** Free-threaded builds use one process and a real thread
  per connection. GIL builds use a bounded thread pool with fast 503 overload shedding and
  can fan out through `SO_REUSEPORT` workers.
- **msgspec request bodies.** JSON decoding and validation happen together in compiled C
  codecs.
- **A small, owned HTTP core.** Routing, parsing, scheduling, draining, and response writes
  are dexpot code—not a wrapper around another web framework.

This is a full framework under active construction. The serving and routing foundation is
shipped; production HTTP features such as middleware, OpenAPI, streaming, authentication,
and hardened parser limits are tracked in the [roadmap](ROADMAP.md).

## Quick start

### 1. Install

```bash
pip install "dexpot[cli]"
```

### 2. Define an application

Create `main.py`:

```python
import msgspec

from dexpot import Dex


class ItemIn(msgspec.Struct):
    name: str
    price: float


class ItemOut(msgspec.Struct):
    id: int
    name: str
    price: float


app = Dex()


@app.get("/items/{item_id}", response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    return ItemOut(id=item_id, name=f"item-{item_id}", price=9.99)


@app.post("/items", body=ItemIn, response=ItemOut)
def create_item(item: ItemIn) -> tuple[int, ItemOut]:
    return 201, ItemOut(id=1, name=item.name, price=item.price)
```

The path capture is converted from text because `item_id` is annotated as `int`. The POST
body is decoded directly into `ItemIn`; malformed JSON or a validation failure returns 422.

### 3. Serve it

```bash
dexpot serve main:app --host 127.0.0.1 --port 8000
```

Call the real HTTP surface:

```bash
curl -s http://127.0.0.1:8000/items/7
curl -s -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"keyboard","price":79.0}'
```

The responses are JSON:

```json
{"id":7,"name":"item-7","price":9.99}
```

```json
{"id":1,"name":"keyboard","price":79.0}
```

You can also run the file directly with `app.serve()`:

```python
if __name__ == "__main__":
    app.serve(host="127.0.0.1", port=8000)
```

## Route contract

Use `@app.get`, `@app.post`, `@app.put`, `@app.patch`, and `@app.delete`.

```python
@app.post(
    "/accounts/{account_id}/items",
    body=ItemIn,
    response=ItemOut,
)
def create_for_account(item: ItemIn, account_id: int) -> ItemOut:
    return ItemOut(id=account_id, name=item.name, price=item.price)
```

The handler signature does not have to mirror URL order. dexpot binds path captures by name,
finds the declared body parameter, preserves Python signature order, and supports
keyword-only parameters. Registration fails before serving when:

- a required parameter has no matching path capture, request body, or default;
- a path capture is not accepted by the handler;
- the handler uses `*args` or `**kwargs`; or
- another route already owns the same method and structural path shape.

For example, `GET /users/{id}` and `GET /users/{name}` conflict because only one can ever
match a request.

A handler may return a JSON-encodable value, a msgspec struct, or `(status, payload)`.
`response=` precompiles the successful-response encoder, but the current release does not
yet enforce the returned type at runtime.

## Execution model

dexpot chooses its scheduler once when the module is imported.

| Runtime | Default serving model | Overload behavior |
|---|---|---|
| Free-threaded CPython (`sys._is_gil_enabled() == False`) | One process; each accepted connection owns a thread | No framework queue; OS and process limits apply |
| Standard GIL CPython | Bounded pool of `CPU * 2 + 2` connection-owning threads | Queue capped at `2 * pool`; excess connections receive 503 |
| Standard GIL CPython with `DEXPOT_WORKERS>1` | POSIX `SO_REUSEPORT` processes, each with its own bounded pool | Each worker sheds independently |

A worker owns a keep-alive connection until it closes. This avoids putting idle keep-alive
sockets back into a shared queue, where they can consume admission capacity and stall a
worker waiting for the next request.

Tune the GIL scheduler before the process imports dexpot:

```bash
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 dexpot serve main:app
```

Use process fan-out on supported POSIX systems:

```bash
DEXPOT_WORKERS=4 dexpot serve main:app
```

`DEXPOT_WORKERS>1` requires POSIX `fork` and `SO_REUSEPORT`; dexpot rejects that setting on
unsupported platforms rather than pretending multiprocess serving is active. Free-threaded
builds intentionally remain single-process because their threads can execute Python in
parallel.

SIGINT and SIGTERM stop admission and allow active connections up to five seconds to drain.
The GIL supervisor restarts a worker that exits unexpectedly.

## Current architecture

```text
HTTP connection
      |
      v
accept + adaptive admission
      |
      +-- free-threaded Python --> connection-owned thread
      |
      +-- GIL Python -----------> bounded worker pool
                                      |
                                      +-- optional SO_REUSEPORT processes
      |
      v
parse request head and body
      |
      v
literal lookup / compiled parametric match
      |
      v
convert captures + msgspec decode/validate
      |
      v
plain Python handler
      |
      v
msgspec encode + one response write
```

A registered `Route` is the boundary between setup and traffic. It owns the immutable
handler plan: body decoder, response encoder, capture conversion metadata, and positional
versus keyword binding. Request processing consumes that plan without inspecting the
handler again.

## Current boundaries

dexpot is alpha software and is not yet recommended for untrusted production traffic.
Today:

- HTTP/1.1 requests with `Content-Length` and keep-alive are supported; chunked request
  bodies are not.
- The parser does not yet enforce request-line, header, body, or idle time limits.
- Query strings and headers are parsed internally but are not yet injectable handler
  parameters.
- There is no middleware, OpenAPI generation, authentication, TLS termination, streaming,
  WebSocket support, or proxy-header policy.
- `response=` selects an encoder but does not validate the handler's return type.
- Uncaught handler exception names and messages currently appear in 500 JSON responses.
  Do not put secrets in exception messages, and place dexpot behind a trusted boundary until
  stable public error handling lands.
- Multiprocess serving is POSIX-only. Windows users must use one process in the current
  release.

These are explicit roadmap items, not hidden features. See [ROADMAP.md](ROADMAP.md) for the
implementation order.

## Give your coding agent dexpot context

Install project-local guidance for Claude Code, Cursor, Windsurf, GitHub Copilot, Cline, or
OpenAI Codex:

```bash
# Auto-detect agents already configured in the project
dexpot add skills

# Or target one explicitly
dexpot add skills --agent claude
dexpot add skills --agent cursor
dexpot add skills --agent windsurf
dexpot add skills --agent copilot
dexpot add skills --agent cline
dexpot add skills --agent codex

# Install into another project
dexpot add skills --path ./my-api
```

The installed skill teaches the shipped route contract, msgspec body model, concurrency
modes, operational boundaries, and verification requirements. Shared Copilot and Codex
instruction files use a bounded managed block, so existing project guidance is preserved.

## CLI reference

```text
dexpot serve <module:attribute> [--host HOST] [--port PORT]
dexpot add skills [--agent AGENT] [--path DIRECTORY]
dexpot version
dexpot --version
```

The CLI extra is optional so applications that call `Dex.serve()` directly do not need
Typer:

```bash
pip install dexpot          # framework runtime
pip install "dexpot[cli]"   # framework runtime + dexpot command
```

## Examples

[`examples/minimal.py`](examples/minimal.py) is the smallest runnable application. The
roadmap calls for examples to grow with the public framework surface: typed writes,
operational configuration, middleware, schema generation, and production deployment will
be added only as those capabilities ship.

## Roadmap

The next work is organized around four gates:

1. harden HTTP parsing and public failure behavior;
2. complete the framework contract with request context, middleware, schemas, and richer
   response handling;
3. publish reproducible GIL and free-threaded benchmarks with correctness parity; and
4. add production operations without replacing the synchronous execution model.

The detailed milestones and non-goals live in [ROADMAP.md](ROADMAP.md).

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md), then read
[`docs/reviewing.md`](docs/reviewing.md) before opening a change. Useful contributions
include:

- executable examples under `examples/`;
- real-client HTTP acceptance tests and malformed-request coverage;
- reproducible `wrk` benchmarks that compare successful equivalent responses;
- parser, shutdown, and overload correctness;
- roadmap features with a focused issue and end-to-end tests; and
- documentation that clearly separates current behavior from planned architecture.

Set up and run the complete local gate with:

```bash
uv sync --all-extras
make check
```

User-facing changes require a Towncrier fragment. See
[`changelog.d/README.md`](changelog.d/README.md).

## License

MIT — see [LICENSE](LICENSE).
