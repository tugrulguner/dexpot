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
- treats the first parameter remaining after path, `Request` and explicit source bindings as the declared body;
- preserves Python signature order;
- supports keyword-only parameters; and
- allows default-only parameters after the body parameter.

Registration fails before serving when a required parameter has no source, a path capture is not accepted, the handler uses `*args` or `**kwargs`, or another route owns the same method and structural path shape.

`GET /users/{id}` and `GET /users/{name}` conflict because only one can match a request.

### Path annotation boundary

Path annotations support only `str`, `int`, unannotated parameters, and `Any`.
Only `int` is converted, with 422 for invalid integers; other supported captures stay strings.
`float`, `bool`, `Enum`, `Annotated`, unions, and explicit `None` are unsupported.
In dexpot 0.8.1 and newer, unsupported path annotations raise `TypeError` during registration
instead of silently receiving strings in v0.8.0. Rejected registrations do not reserve the
route or invoke the handler. To migrate, use `str` and explicit application validation,
or a typed JSON body where appropriate. JSON body and response schemas have separate rules.

## Typed input sources

Included in v0.9.0: typed query/header/cookie inputs.
Use source containing this feature. A public-index v0.8.1 installation cannot run the new
declarations. The existing path rules above remain unchanged, including rejection of
`Annotated` path captures.

```python
from typing import Annotated
from dexpot import Cookie, Dex, Header, Query

app = Dex()

@app.get('/items')
def list_items(
    limit: Annotated[int, Query('limit')] = 20,
    *,
    request_id: Annotated[str, Header('x-request-id')],
    theme: Annotated[str, Cookie('theme')] = 'light',
):
    return {'limit': limit, 'request_id': request_id, 'theme': theme}
```

### Registration

Supply an explicit wire name and exactly one Query, Header or Cookie marker inside Annotated.
Only exact base types str/int/float/bool are supported. Reject Any, Enum, Literal, unions/Optional,
collections, Structs, NewType and additional metadata. Immutable markers and source/name/type/default
errors fail registration atomically; duplicate normalized (source, alias) bindings are rejected.
Header aliases become lowercase; query/cookie names are case-sensitive. No underscore-to-hyphen
or Unicode normalization. Query names are nonempty UTF-8-encodable strings without controls;
header/cookie names are nonempty ASCII HTTP tokens.

No Python default means required. Defaults must have the exact declared type: True is not an
int default, 1 is not a float default, and None/non-finite floats are rejected. Do not execute
application factories. Marked parameters are excluded before selecting the declared body.
Existing unmarked defaults, Request, annotation namespaces and signature order are preserved.

### Extraction and cardinality

Missing selects a valid default or returns 422. Empty text is present: valid for str, invalid
for numeric/bool inputs. Invalid present data never falls back to a default.

- Query: split on `&` and the first `=`, preserve bare names as empty values, ignore empty
  segments and do not split semicolons. Decode names with strict UTF-8 percent decoding and
  plus-as-space before matching: limit and %6cimit are duplicates. Decode only requested
  values. Unknown values (including %FF) and unknown duplicates are ignored. Undecodable names
  fail the typed query source; repeated requested keys fail even if values agree.
- Headers: use the existing lowercase dictionary and outer-whitespace-normalized values.
  Physical duplicates are already comma-folded: str sees `1, 2`, while int rejects it. Do not
  claim physical-duplicate detection or treat header presence as authentication.
- Cookies: parse only for Cookie bindings. Absent/empty headers have no pairs. Split the
  semicolon-joined header, remove surrounding SP/HTAB pair framing, then split the first `=`.
  Names are ASCII tokens. Values use RFC 6265 cookie-octet syntax, optionally surrounded by
  one balanced double-quote pair; empty values are supported. No backslash escapes, quoted
  semicolons/commas, non-ASCII values, URL/plus decoding or trimming inside values. Empty
  segments in a nonempty header and malformed pairs fail, including malformed unknown pairs.
  Well-formed unknown names/duplicates are ignored; repeated requested names fail.

`Header('cookie')` str reads raw normalized text without activating cookie parsing. Malformed
escape syntax such as %GG remains parser-level 400 on every route. Valid escape syntax %FF
stays raw on an unmarked Request route; selected typed query values reject invalid UTF-8 with
422. Raw Request.query and Request.headers are never replaced with converted views.

### Conversion

Convert extracted text without further trimming. Strings are unchanged (query UTF-8, existing
header Latin-1, cookie ASCII). Integers match signed ASCII decimal digits only, then convert
under Python's unchanged safety limit; no whitespace, Unicode digits, underscores or points.
Floats use the following full-match grammar and must convert to a finite value:

```text
[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?
```

Reject NaN/Infinity, hex and overflow; finite underflow to signed zero is accepted. Booleans
accept ASCII true/false case-insensitively, never 0/1, yes/no, on/off or Python truthiness.
Query `+7` becomes a leading space and fails int conversion; use %2B7 for a plus sign.
Literal null is text, not None. These rules do not tighten the legacy path converter or
replace the richer JSON body/response schemas.

### Errors and lifetime

The detail-only JSON envelope uses messages such as `query parameter 'limit': invalid`.
Reasons are missing, repeated, invalid or selected-value encoding. Source-wide errors are
`invalid query encoding` and `invalid cookie header`. These are 422 responses; aliases are
declared names (headers lowercase), never supplied values. New input errors/logs do not echo
values, authorization/cookie contents or conversion exceptions.

Error precedence remains protocol/framing, routing, path conversion and JSON body decoding;
marked inputs then validate in handler declaration order. Parse a source lazily at its first
binding; its structural errors precede per-binding checks there. Return only the first error
before the handler runs. Keep-alive/pipelining recovery, HEAD body suppression and method
matching are unchanged. Decoded state belongs to one request, not a route or reused connection.
Typed-only handlers need no public Request allocation; unmarked routes do not parse query/cookie
data. Typed binding does not implicitly enable OpenAPI, DI, lists/repeated-value binding, public lazy views or proxy trust.

The [typed-input example](https://github.com/tugrulguner/dexpot/blob/main/examples/typed_inputs.py)
requires dexpot 0.9.0 or newer.

## OpenAPI export

Included in v0.9.0: OpenAPI export.
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
or `__annotations__`) or native field/default metadata with opaque descriptors;
ordinary/native descriptors remain supported.
Custom fallback attribute getters cannot fabricate schema metadata; standard enum
attribute lookup remains supported.
Model annotations, referenced aliases, defaults and schema metadata must stay unchanged
from their first native/msgspec use. Captured models have weak, identity-based process-wide
fingerprints: later conflicting captures reject across routes and applications, while existing
snapshots remain intact. Declare a new model type for a new contract. The exporter cannot
reconstruct bindings from an external native cache created before its first capture; changing
a model in that unobserved interval is unsupported.

```python
from dexpot import Dex

app = Dex(openapi=True)

@app.get("/items/{item_id}", response=int)
def item(item_id: int):
    return item_id

schema = app.openapi(title="Example API", version="development")
```

Registration snapshots remain authoritative even if annotations later change. Schema generation
never calls application default factories; factory-derived defaults are not fabricated. Non-finite
schema defaults and unrepresentable declarations are rejected atomically on opt-in registration.
A failed export does not freeze an otherwise mutable application. Callers may mutate the returned
document without changing runtime plans or subsequent exports. Components are namespaced per
operation/role to avoid cross-route name collisions; generated component names are not a stable API.

See [the complete runnable example](https://github.com/tugrulguner/dexpot/blob/main/examples/openapi.py).

## Responses

A handler may return:

- a JSON-encodable value;
- a msgspec struct; or
- `(status, payload)`.

`response=T` strictly validates and projects the returned value onto the public schema, including malformed existing/nested Structs. Ordinary Struct schemas drop extra fields; `forbid_unknown_fields=True` rejects them. `response=None` uses generic JSON encoding without validation or filtering. Checked output rejects non-finite floats, including optional, nested, Any and default values. Custom schema types and schemas containing `__post_init__` or `__attrs_post_init__` hooks fail atomically at registration. Invalid output returns a sanitized 500 before success bytes are sent.

<figure>
  <img src="/dexpot-response-contract.webp?v=070-response-v1" alt="For response=T, the handler result is schema-validated and projected to public fields before encoding and sending. Malformed or non-finite output instead returns a sanitized 500 before success bytes. response=None keeps generic encoding; RawResponse is only permitted on unchecked routes." />
  <figcaption>Checked response flow: public projection removes undeclared fields; invalid output takes the sanitized error branch before success bytes. Application factories stay deferred, checked fallbacks preserve schema semantics, and envelopes are shallowly immutable.</figcaption>
</figure>

[Open the response-contract diagram at full size](/dexpot-response-contract.webp?v=070-response-v1).

The diagram is a contract overview, not a promise of a literal single pass or exact Python type-identity validation. Dexpot applies msgspec-compatible conversions (an integer can satisfy a float field); preparation preserves default semantics and the registered factory objects. Static default checks run at registration, but arbitrary application factories are not invoked during registration. Free-threaded macOS nested preparation is fully checked before encoding or socket I/O. Sets and native-only scalar schemas retain checked native fallbacks.

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


## Database resource example

The repository's `examples/database.py` uses existing synchronous `app.lifespan(factory)`
(dexpot 0.8.0 or newer), ordinary context managers and stdlib SQLite. This is not
request-scoped dependency injection. A bounded process-local pool owns connections; each
handler exclusively leases a connection and returns it on every exit. Exhaustion is 503.
Thread sharing is explicit; GIL processes replicate pool capacity, and a keep-alive HTTP
connection does not retain a lease between requests. Normal shutdown retains resources for
active handlers; forced termination need not run Python cleanup.

In this example, item IDs outside SQLite's signed 64-bit range return 404 before a
connection lease, without changing the framework's integer path conversion.
Input validation precedes handler side effects. A handler-local transaction rolls back on
an exception inside that transaction. An encoding failure after commit can still return
500 while leaving the write committed, because checked response preparation follows handler
return. Do not promise rollback on every 500 or atomic database/remote HTTP delivery.
Use the runnable example and `examples/README.md` for the bounded demonstration; no hooks,
scoped factory graph, proxy trust or new runtime API is introduced.

The source-checkout retry walkthrough adds `POST /retry-safe/items` and the runnable client
`uv run python examples/database.py --retry-demo`. It generates an operation ID once,
deliberately fails the first reply after commit, and retries the same operation ID and
validated payload to recover the original 201 result without another insert. The item and
operation record commit in the same database transaction; a conflicting payload for an
existing ID returns 409. The mapping survives restart with the same SQLite file. This is
application-owned deduplication, not a framework retry feature. Its fault header is for
local demonstrations only. Operation IDs are not authentication, and deleting the mapping
removes replay protection. The ordinary `/items` route remains unsafe to retry blindly;
database commits and remote HTTP delivery are still not atomic.
