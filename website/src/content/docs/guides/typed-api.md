---
title: Build a typed JSON API
description: A complete route-binding workflow with request validation, context, status responses, error checks, and real HTTP execution.
---

**Prerequisites:** Python 3.12+, Dexpot with its CLI, and a terminal. Create a project and install the framework before following this guide:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install 'dexpot[cli]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. This guide uses a local-only listener; it does not expose the example to a network.

## 1. Declare the wire shapes and routes

Save as `main.py`:

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

@app.get('/items/{item_id}', response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    return ItemOut(item_id, f'item-{item_id}', 9.99)

@app.post('/items', body=ItemIn, response=ItemOut)
def create_item(item: ItemIn) -> tuple[int, ItemOut]:
    return 201, ItemOut(1, item.name, item.price)
```

The explicit `body=ItemIn` selects and precompiles a msgspec JSON decoder; the matching handler parameter receives the decoded `ItemIn`. A path capture is converted according to the `int` annotation. `response=ItemOut` precompiles the successful response encoder; it does **not** enforce the returned value's type at runtime. Annotate an optional `request: Request` parameter to receive the frozen public request context; see [routes and handlers](/route-contract/#request-context).

## 2. Run and exercise the public HTTP interface

```bash
dexpot serve main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
curl -i http://127.0.0.1:8000/items/7
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"keyboard","price":79.0}'
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' -d '{"name":false}'
curl -i -X PUT http://127.0.0.1:8000/items
```

The first request returns a JSON `ItemOut` with id 7. The valid POST returns status 201 and the submitted name and price. Invalid JSON or body validation returns 422; a path that exists only for another method returns 405 with `Allow`. These are deterministic contract expectations; consult the linked response checks for the repository's executable examples.

## 3. Verify against the repository

The repository's socket-level example test launches each example as a subprocess and checks actual HTTP responses:

```bash
uv sync --all-extras
uv run pytest tests/test_examples.py -q
```

See [`examples/typed_crud.py`](https://github.com/tugrulguner/dexpot/blob/main/examples/typed_crud.py) for mutable CRUD state and application-owned locking. Do not share mutable state between concurrent handlers without synchronization. For binding details—including positional and keyword-only parameters, registration failures, postponed annotations, and `annotation_locals`—continue to [routes and handlers](/route-contract/). For bounded limits and parser behavior, read the [HTTP boundary](/http-boundary/).

[Download this guide as Markdown](/guides/typed-api.md).
