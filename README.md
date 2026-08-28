# dexpot

<p align="center">
  <img src="https://raw.githubusercontent.com/tugrulguner/dexpot/main/assets/dexpot.png" alt="dexpot synchronous Python API framework" width="600">
</p>

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
  <a href="https://discord.gg/u3AANZr6RG"><img src="https://img.shields.io/badge/Discord-Join%20ModePot-5865F2?logo=discord&amp;logoColor=white" alt="Join the ModePot Discord"></a>
  <a href="https://github.com/tugrulguner/dexpot/stargazers"><img src="https://img.shields.io/github/stars/tugrulguner/dexpot?style=flat" alt="GitHub stars"></a>
  <a href="https://github.com/tugrulguner/dexpot/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-dexpot">Why dexpot</a> ·
  <a href="#execution-model">Execution model</a> ·
  <a href="#current-boundaries">Boundaries</a> ·
  <a href="#examples">Examples</a> ·
  <a href="#community">Community</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/tugrulguner/dexpot/main/docs/assets/dexpot-execution.png" alt="A dexpot route compiles once into an immutable endpoint plan, parses each bounded request head with compatible dexpot-native or the Python reference when native is absent, then uses either a connection-owned thread on free-threaded CPython or a bounded worker pool with optional process fan-out on standard GIL CPython before both paths execute the same synchronous handler pipeline" width="960">
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

dexpot is alpha software and is not yet recommended for untrusted production traffic. Its
socket core now fails closed on malformed framing and enforces request limits, but production
operations such as access logging, metrics, trusted-proxy policy, TLS guidance, middleware,
OpenAPI, streaming, and authentication remain on the [roadmap](ROADMAP.md).

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

### HTTP limits

Every connection enforces conservative defaults: an 8 KiB request line, 64 KiB request head,
100 headers, a 16 MiB body, a five-second idle read timeout, a ten-second absolute head
deadline, and a thirty-second absolute body deadline. Override them as one typed, immutable
policy rather than adding transport options to route decorators:

```python
from dexpot import Dex, HttpLimits

app = Dex(
    limits=HttpLimits(
        request_line_bytes=4 * 1024,
        header_bytes=32 * 1024,
        header_count=64,
        body_bytes=2 * 1024 * 1024,
        idle_read_seconds=10.0,
        head_read_seconds=15.0,
        body_read_seconds=60.0,
    )
)
```

Values must be positive, and the total request-head allowance must exceed the request-line
allowance. Oversized or timed-out requests receive a stable error and the connection closes.

### Parser backend

The pure-Python request-head parser remains the behavioral reference and fallback. An
experimental `dexpot-native` subproject provides the same request-line, header, Host,
framing, and keep-alive semantics through a parser-only PyO3 extension. Python still owns
sockets, deadlines, bodies, pipelining, target decoding, routing, handlers, scheduling, and
worker supervision.

Backend selection happens once when dexpot is imported:

```bash
DEXPOT_HTTP_PARSER=python dexpot serve main:app  # force the Python reference parser
DEXPOT_HTTP_PARSER=native dexpot serve main:app  # require dexpot-native
DEXPOT_HTTP_PARSER=auto dexpot serve main:app    # default: native if installed, else Python
```

`native` fails clearly when the extension is unavailable. The default `auto` mode falls back
only when the native module is absent; ABI and initialization failures remain visible. The
accelerator is not yet published, so installing or building it remains the opt-in decision.
Contributors can build it from
[`native/`](native/README.md); its wheel matrix, parity suite, and promotion gates are tracked
in [issue #18](https://github.com/tugrulguner/dexpot/issues/18).

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
treats the first non-path parameter as the declared body, preserves Python signature order,
and supports keyword-only parameters. Put default-only parameters after that body parameter.
Registration fails before serving when:

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

A registered `Route` separates setup from traffic. It owns the immutable handler plan:
literal or parametric matching, body and response codecs, capture conversions, and
positional versus keyword binding. Request processing consumes that plan without
inspecting the handler again.

Parser selection is orthogonal to scheduling: each bounded request head uses a compatible
`dexpot-native` installation when present and otherwise the Python reference parser. Python
continues to own sockets, deadlines, bodies, and routing.

The interpreter changes admission and scheduling, not application code. Free-threaded
CPython gives each accepted connection its own thread in one process. Standard GIL CPython
uses a bounded pool, sheds excess work with 503, and can add POSIX process fan-out. Both
paths enforce the same HTTP limits and execute the same compiled route, synchronous
handler, and msgspec response pipeline shown above.

## Current boundaries

The current alpha release has these boundaries:

- HTTP/1.0 and HTTP/1.1 requests with validated `Content-Length` framing are supported;
  transfer encodings, including chunked request bodies, are rejected and the connection closes.
- Request-line, total-header, header-count, and body limits plus idle and absolute head/body
  deadlines are enforced before request data can accumulate or drip indefinitely.
- Request targets are currently origin-form only (`/path?query`); absolute-form proxy targets
  are rejected during this alpha milestone.
- The optional native request-head parser is experimental. Automatic detection is the default,
  but it activates Rust only when the separately installed extension is present; Python remains
  the reference and fallback.
- Routing distinguishes 404 from 405, returns `Allow` for method mismatches, percent-decodes
  UTF-8 paths safely, and treats duplicate or trailing slashes as distinct paths.
- Query strings and headers are parsed internally but are not yet injectable handler
  parameters.
- There is no middleware, OpenAPI generation, authentication, TLS termination, streaming,
  WebSocket support, or proxy-header policy.
- `response=` selects an encoder but does not validate the handler's return type.
- Uncaught handler exceptions produce a stable public 500 body while the traceback is logged
  server-side. Structured logging and request IDs remain production-operations work.
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

The CLI extra is optional, so applications that call `Dex.serve()` directly do not need
Typer:

```bash
pip install dexpot          # framework runtime
pip install "dexpot[cli]"   # framework runtime + dexpot command
```

## Examples

The runnable progression under [`examples/`](examples/README.md) exercises the shipped framework
through its real socket server:

- [`minimal.py`](examples/minimal.py): typed path capture and response;
- [`typed_crud.py`](examples/typed_crud.py): thread-safe shared state, typed JSON writes, and a
  complete create/read/update/delete lifecycle; and
- [`bounded_api.py`](examples/bounded_api.py): custom `HttpLimits`, 413/422 failures, and 405
  method handling.

Each example runs directly with `uv run python examples/<name>.py`, and the test suite launches
every example as a subprocess and validates its public HTTP behavior. Examples will continue to
grow only as middleware, schemas, deployment support, and other roadmap capabilities ship.

## Roadmap

The shipped foundation now includes the HTTP-hardening gate and the optional native
request-head seam. Remaining work is organized around four gates:

1. complete the framework contract with request context, middleware, schemas, and richer
   response handling;
2. publish reproducible GIL and free-threaded benchmarks with correctness parity; and
3. add production operations without replacing the synchronous execution model; and
4. grow runnable examples, testing support, deployment guidance, and stable extension points.

The detailed milestones and non-goals live in [ROADMAP.md](ROADMAP.md).

## Community

The [ModePot Discord](https://discord.gg/u3AANZr6RG) is the shared community for dexpot,
intpot, summonpot, and the rest of the project family. Join to discuss synchronous API
design, free-threaded Python, implementation questions, and real application use cases.

Use GitHub [issues](https://github.com/tugrulguner/dexpot/issues/new/choose) for
reproducible bugs and scoped feature proposals. Use
[Discussions](https://github.com/tugrulguner/dexpot/discussions) for durable project Q&A,
and Discord for exploratory design, early ideas, and cross-project help.

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

Open an issue before substantial handler, routing, parser, scheduler, protocol, or execution
contract work. Focused fixes, tests, documentation, and maintenance may be direct pull
requests when they do not introduce a new public contract.

Set up and run the complete local gate with:

```bash
uv sync --all-extras
make check
```

User-facing changes require a Towncrier fragment. See
[`changelog.d/README.md`](changelog.d/README.md).

## Support dexpot

- Run one of the checked-in examples and report any friction through the
  [issue forms](https://github.com/tugrulguner/dexpot/issues/new/choose).
- Share a real synchronous API or free-threaded Python use case in
  [Discussions](https://github.com/tugrulguner/dexpot/discussions) or the
  [ModePot Discord](https://discord.gg/u3AANZr6RG).
- If dexpot's execution model is useful to you, use the Star control on the
  [repository](https://github.com/tugrulguner/dexpot) so other Python developers can find it.

## License

MIT — see [LICENSE](LICENSE).
