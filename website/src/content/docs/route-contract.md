---
title: Routes and handlers
description: Dexpot route registration, handler binding, msgspec request bodies, response encoding, annotation namespaces, and request context.
---

Use `@app.get`, `@app.post`, `@app.put`, `@app.patch`, and `@app.delete`. For a complete runnable typed request/response path, see [Build a typed JSON API](/guides/typed-api/); this page is the symbol-level contract.

```python
@app.post(
    "/accounts/{account_id}/items",
    body=ItemIn,
    response=ItemOut,
)
def create_for_account(item: ItemIn, account_id: int) -> ItemOut:
    return ItemOut(id=account_id, name=item.name, price=item.price)
```

## Handler binding

The handler signature does not have to mirror URL order. Dexpot:

- binds path captures by name;
- treats the first non-path, non-`Request` parameter as the declared body;
- preserves Python signature order;
- supports keyword-only parameters; and
- allows default-only parameters after the body parameter.

Registration fails before serving when a required parameter has no source, a path capture is not accepted, the handler uses `*args` or `**kwargs`, or another route owns the same method and structural path shape.

`GET /users/{id}` and `GET /users/{name}` conflict because only one can match a request.

## Responses

A handler may return:

- a JSON-encodable value;
- a msgspec struct; or
- `(status, payload)`.

`response=` precompiles the successful-response encoder. The current release does not yet enforce the returned type at runtime.

## Annotation namespaces

Route decorators never read caller locals. Postponed annotations resolve against the handler module globals and captured closure bindings. For annotation-only aliases local to a factory or class, pass the exact bindings explicitly:

```python
from __future__ import annotations
from dexpot import Dex


def build():
    from dexpot import Request as Context

    app = Dex()

    @app.get("/context", annotation_locals={"Context": Context})
    def context(request: Context):
        return {"method": request.method}

    return app
```

Pass only the required names, not an entire frame's `locals()`. Dexpot shallow-copies `annotation_locals` when the decorator is created.

## Request context

Annotate a parameter with the public `Request` type:

```python
from dexpot import Request


@app.post("/accounts/{account_id}/items", body=ItemIn)
def create_with_context(item: ItemIn, account_id: int, *, request: Request) -> dict:
    return {
        "account_id": request.params["account_id"],
        "method": request.method,
        "query": request.query,
        "same_body": request.body is item,
    }
```

The request object is allocated only for handlers that ask for it. It is frozen and contains the decoded route values, raw query string, lowercase headers, received body bytes, and the same validated body object passed to the handler.
