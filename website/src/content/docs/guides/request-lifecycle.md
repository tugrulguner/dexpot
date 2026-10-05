---
title: Trace a request through Dexpot
description: Follow the actual ownership path from decorators and immutable plans through parsing, scheduling, binding, and response writing.
---

This is an internals guide for maintainers and agents investigating the boundary between an endpoint declaration and an HTTP response. Public contract details remain in [routes and handlers](/route-contract/), the [execution model](/execution-model/), and the [HTTP boundary](/http-boundary/).

## Declaration and compilation

`Dex.get`, `post`, `put`, `patch`, and `delete` return decorators. Decoration validates route shape and handler binding, resolves annotations against module globals and any explicit `annotation_locals`, and constructs an `EndpointPlan`. The plan retains the callable, route metadata, parameter-binding operations, optional msgspec body decoder, and optional successful-response encoder. `annotation_locals` is shallow-copied; closure bindings take precedence. Caller frames are not inspected.

`Dex.serve()` freezes the application before opening the listener. `RouterPlan.compile(...)` groups routes for matching and rejects structural method/path conflicts. `ApplicationPlan` holds the router plan and endpoint plans used for requests. Plans are immutable; registering additional routes after freeze raises rather than making live traffic diverge from declarations. Trace implementation in [`app.py`](https://github.com/tugrulguner/dexpot/blob/main/src/dexpot/app.py), [`_plans.py`](https://github.com/tugrulguner/dexpot/blob/main/src/dexpot/_plans.py), and tests for [`application plans`](https://github.com/tugrulguner/dexpot/blob/main/tests/test_application_plan.py).

## Connection and request dataflow

```text
accept -> scheduler admission -> connection-owning worker
       -> bounded request-head accumulation and parse
       -> framing/limits checks -> route match and method check
       -> path conversion + body decode/validation + Request injection
       -> synchronous handler -> status/payload normalization
       -> JSON encoding + response write -> next keep-alive request or close
```

The Python socket server owns deadlines, request bodies, pipelining, target decoding, routing, handler invocation, scheduling, and worker supervision. `msgspec` provides typed JSON decode/validation and JSON encoding. `response=` selects a precompiled encoder; it does not runtime-check the returned type. Handler exceptions are logged server-side and map to a stable public 500 response. Binding and validation errors are distinguished from unknown routes and unsupported methods; see the detailed [route contract](/route-contract/).

## Parser selection is not server selection

`DEXPOT_HTTP_PARSER=python|native|auto` is read when `dexpot.app` imports. `auto` uses the compatible optional `dexpot-native` parser when available and otherwise the Python reference parser; it falls back only when the native module is absent. ABI or initialization errors remain visible. `native` requires the extension. The Rust/PyO3 component parses request heads only; it is not an alternate HTTP server and does not own sockets, body reads, routing, or scheduling. See [`_http.py`](https://github.com/tugrulguner/dexpot/blob/main/src/dexpot/_http.py) and [`test_parser_backend.py`](https://github.com/tugrulguner/dexpot/blob/main/tests/test_parser_backend.py).

## Where to investigate a symptom

- Registration or annotation failure: decorator and `_plans.py`; `tests/test_application_plan.py`.
- Wrong method, path, body, or status: route matching/invocation in `app.py`; `tests/test_e2e.py`.
- Malformed framing, timeout, partial body, or keep-alive: `_http.py` and socket tests in `tests/test_http_hardening.py`.
- Saturation, shutdown, worker restart, or listener lifecycle: admission and serving/supervisor paths in `app.py`; `tests/test_http_hardening.py` and `tests/test_multiprocess.py`.

For the protocol and rejection matrix, see [HTTP boundary](/http-boundary/). For runtime branches and capacity defaults, see [execution model](/execution-model/).

[Download this guide as Markdown](/guides/request-lifecycle.md).
