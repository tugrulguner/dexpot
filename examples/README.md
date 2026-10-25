# Runnable examples

These examples form a small progression over dexpot's shipped public surface. Run each file
from the repository root after `uv sync --all-extras`:

```bash
uv run python examples/minimal.py
uv run python examples/typed_crud.py
uv run python examples/bounded_api.py
uv run python examples/lifecycle.py
```

Set `DEXPOT_EXAMPLE_PORT` when port 8000 is already in use.

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

## Execution modes

The application code does not change between interpreters:

```bash
# Tune bounded GIL threads and admission queue.
DEXPOT_POOL=16 DEXPOT_MAX_QUEUE=32 uv run python examples/typed_crud.py

# Fan out across process-local SO_REUSEPORT listeners on supported POSIX GIL builds.
DEXPOT_WORKERS=4 uv run python examples/typed_crud.py

# Tune the free-threaded active-connection cap (default: 1024).
DEXPOT_MAX_CONNECTIONS=512 uv run python examples/typed_crud.py

# A free-threaded CPython build is detected automatically and uses one process with
# capped connection-owning threads that can execute Python in parallel.
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


## Paired application lifecycle

Register synchronous context-manager factories with `app.lifespan(factory)`. Registration and
plan compilation do not call the factory. Each serving process enters factories in order before
accepting traffic and normally exit them in reverse order after active handlers finish. Shutdown waits
for a bounded drain deadline; if handlers remain, cleanup is deferred until they finish. A factory
that fails to enter aborts startup and already-entered managers are unwound. Forced process
termination may skip Python cleanup. These resources are
process-owned: GIL worker processes each acquire their own copy; free-threaded serving threads
share the serving process's acquired resources, so those resources must be thread-safe.

```python
import contextlib
from dexpot import Dex

app = Dex()

@contextlib.contextmanager
def database_pool():
    pool = create_pool()
    try:
        yield
    finally:
        pool.close()

app.lifespan(database_pool)
```

A disconnected client does not cancel Python handler work. Shutdown drains for a bounded period; if
handlers remain, their connections and application resources are left untouched and cleanup runs
when the last handler finishes. In a single-process embedded caller, serve returns after the deadline
without killing the host interpreter; resources remain owned until quiescence. Forced process
termination may skip Python cleanup.
