# Runnable examples

These examples form a small progression over dexpot's shipped public surface. Run each file
from the repository root after `uv sync --all-extras`:

```bash
uv run python examples/minimal.py
uv run python examples/typed_crud.py
uv run python examples/bounded_api.py
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

# A free-threaded CPython build is detected automatically and uses one process with
# connection-owning threads that can execute Python in parallel.
```

Dexpot is still alpha software. These examples validate the current framework contract; they
are not production deployment recipes. See the root README and roadmap for current boundaries.
