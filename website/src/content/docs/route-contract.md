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

`response=T` strictly validates and projects the returned value onto the public schema, including malformed existing/nested Structs. Ordinary Struct schemas drop extra fields; `forbid_unknown_fields=True` rejects them. `response=None` uses generic JSON encoding without validation or filtering. Checked output rejects non-finite floats, including optional, nested, Any and default values. Custom schema types and schemas containing `__post_init__` or `__attrs_post_init__` hooks fail atomically at registration. Invalid output returns a sanitized 500 before success bytes are sent.

`Response(body=None, status=200, headers=())` adds JSON metadata with a copied header snapshot; pair sequences preserve duplicates. `RawResponse(body=b"", status=200, headers=(), content_type="application/octet-stream")` requires bytes and `response=None`. Envelopes are shallowly immutable. Status must be an integer (not bool), 200..599. Headers are bounded to 64 pairs/16,384 encoded bytes, with token names and Latin-1 values without controls. Framing/server headers and Content-Type cannot be overridden; use raw `content_type` (nonempty, at most 256 characters).

`Response(status=204)` (also 205/304) explicitly permits an absent checked body. Other JSON bodies are validated before bodyless suppression. 204/304 omit Content-Length; 205 sends length zero. `RawResponse()` sends an empty 200. Raw output cannot bypass a checked schema. Existing `(status, payload)` returns remain supported.

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
