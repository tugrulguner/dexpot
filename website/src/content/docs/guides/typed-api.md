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

The explicit `body=ItemIn` selects and precompiles a msgspec JSON decoder; the matching handler parameter receives the decoded `ItemIn`. A path capture is converted according to the `int` annotation. `response=ItemOut` strictly validates and projects the returned value onto the public schema; invalid output produces a sanitized 500. Annotate an optional `request: Request` parameter to receive the frozen public request context; see [routes and handlers](/route-contract/#request-context).

Path annotations support only `str`, `int`, unannotated parameters, and `Any`.
`float`, `bool`, `Enum`, `Annotated`, unions, and explicit `None` are unsupported.
In dexpot 0.8.1 and newer, unsupported path annotations raise `TypeError` during registration
instead of silently receiving strings as in v0.8.0. This is separate from the richer
JSON body and response schema support shown above. For raw string captures, validate and
convert explicitly in application code before numeric comparisons or boolean decisions.

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

## 4. Explicit scalar inputs from source (unreleased)

Unreleased: typed query/header/cookie inputs. Public v0.8.1 does not include these markers.
The public-install workflow above remains valid for JSON APIs; use a source checkout containing
this feature for `Annotated[T, Query('name')]`, `Header('name')` and `Cookie('name')`.

From that checkout, run:

```bash
uv sync --all-extras
uv run python examples/typed_inputs.py
```

In another terminal:

```bash
curl -i 'http://127.0.0.1:8000/items/drinks?limit=1&min_price=3&include_archived=false' \
  -H 'X-Request-ID: example-1' -H 'Cookie: theme=dark'
curl -i 'http://127.0.0.1:8000/items/drinks?include_archived=yes' \
  -H 'X-Request-ID: example-2'
```

The example applies query pagination/filtering, a required request-id header and a cookie
preference. The first call uses converted int/float/bool arguments; the second returns 422
before the handler. Request-id is trace metadata, not authentication. Defaults apply only to
missing values. Only exact str/int/finite float/bool are supported. Requested query/cookie
duplicates fail; headers retain normalized/comma-folded behavior. Path converters are unchanged.
See [typed input sources](/route-contract/#typed-input-sources-unreleased) for encoding/cookie
rules, defaults, sanitized errors and precedence. Typed binding does not implicitly enable OpenAPI or DI.

## 5. Export the source-only OpenAPI contract

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
Postponed model annotations follow native module-before-class lookup, including
PEP 695 type parameters; class-local aliases remain fallbacks when unshadowed.
Generic-model availability still follows native interpreter/msgspec support.
Opaque module namespace getters, including replacement `__dict__` descriptors,
are rejected before the exporter reads their namespace.
Model metaclasses may not replace structural metadata readers (such as `__dict__`
or `__annotations__`) with opaque descriptors; ordinary/native descriptors remain supported.
Model annotations, referenced aliases, defaults and schema metadata must stay unchanged
from their first native/msgspec use. Captured models have weak, identity-based process-wide
fingerprints: later conflicting captures reject across routes and applications, while existing
snapshots remain intact. Declare a new model type for a new contract. The exporter cannot
reconstruct bindings from an external native cache created before its first capture; changing
a model in that unobserved interval is unsupported.

Run the complete source example (not a public v0.8.1 install):

```bash
uv run python examples/openapi.py
curl -s http://127.0.0.1:8000/openapi.json
curl -i -X POST 'http://127.0.0.1:8000/items/7?limit=2' \
  -H 'Content-Type: application/json' -H 'X-Request-ID: example' \
  -d '{"name":"tea","price":3.5}'
```

The example explicitly registers its document route and serves a precomputed JSON snapshot;
requests do not regenerate schemas. The valid POST returns 201. Replacing `limit=2` with
`limit=bad` returns 422 before the handler. To write a file without opening a listener:

```bash
uv run python examples/openapi.py --export openapi.json
```

[Download this guide as Markdown](/guides/typed-api.md).
