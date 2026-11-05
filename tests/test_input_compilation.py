"""Source compilation preserves ordinary calls and the unused-feature fast path."""

from __future__ import annotations

import functools
import http.client
import json
import socket
import typing
from typing import Annotated, Any

from dexpot import Dex, Header, Query
from dexpot._inputs import bind_inputs
from dexpot._plans import EndpointPlan


def invoke(handler: Any, query: str = "v=7", namespace: dict[str, Any] | None = None) -> Any:
    plan = EndpointPlan("GET", "/value", handler, None, None, "", [], namespace)
    values = bind_inputs(plan.input_bindings, query, {})
    return plan.invoke([], None, values)


def test_keyword_positional_only_partial_and_wrapped_sources():
    def original(prefix, value: Annotated[int, Query("v")], /, *, tail=2):
        return prefix, value, tail

    assert invoke(functools.partial(original, "prefix")) == ("prefix", 7, 2)

    def target(*, value: Annotated[int, Query("v")]):
        return value

    @functools.wraps(target)
    def wrapper(*args, **kwargs):
        return target(*args, **kwargs)

    assert invoke(wrapper) == 7


def test_callable_and_class_source_annotations_use_their_original_namespace():
    class CallableHandler:
        def __call__(self, value: Annotated[int, Query("v")]):
            return value

    assert invoke(CallableHandler()) == 7

    class ClassHandler:
        def __init__(self, value: Annotated[int, Query("v")]):
            self.value = value

    assert invoke(ClassHandler).value == 7


def test_annotation_namespace_and_route_values_are_not_shared():
    def handler(value):
        return value

    handler.__annotations__ = {"value": "Alias"}
    assert invoke(handler, "one=1", {"Alias": Annotated[int, Query("one")]}) == 1
    assert invoke(handler, "two=2", {"Alias": Annotated[int, Query("two")]}) == 2


def _exchange(app, headers=b"", target=b"/value?%FF=unrequested"):
    server, client = socket.socketpair()
    with server, client:
        server.settimeout(3)
        client.settimeout(3)
        client.sendall(
            b"GET "
            + target
            + b" HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
            + headers
            + b"\r\n"
        )
        keep_alive, remainder = app._process(server, b"")
        assert not keep_alive and remainder == b""
        response = http.client.HTTPResponse(client)
        response.begin()
        assert response.status == 200
        return json.loads(response.read())


def test_unmarked_http_route_bypasses_input_reader_and_request_allocation(monkeypatch):
    import dexpot.app as application

    app = Dex()
    app.get("/value")(lambda: {"ok": True})
    app._compile()

    def forbidden(*args, **kwargs):
        raise AssertionError("unused input machinery was invoked")

    monkeypatch.setattr(application, "bind_inputs", forbidden)
    monkeypatch.setattr(application, "Request", forbidden)
    assert _exchange(app, b"Cookie: malformed\r\n") == {"ok": True}
    plan = app._endpoints[0]
    assert plan.input_bindings == ()
    assert plan.invoke.__code__.co_varnames[:3] == ("captures", "body", "_handler")


def test_header_only_http_route_avoids_other_parsers_request_and_typing_inspection(monkeypatch):
    import dexpot._inputs as inputs
    import dexpot.app as application

    app = Dex()

    @app.get("/value")
    def handler(value: Annotated[int, Header("x-value")]):
        return {"value": value}

    app._compile()

    def forbidden(*args, **kwargs):
        raise AssertionError("unrequested source or runtime introspection was invoked")

    monkeypatch.setattr(inputs, "_query_pairs", forbidden)
    monkeypatch.setattr(inputs, "_cookie_pairs", forbidden)
    monkeypatch.setattr(application, "Request", forbidden)
    monkeypatch.setattr(typing, "get_origin", forbidden)
    monkeypatch.setattr(typing, "get_args", forbidden)
    assert _exchange(app, b"X-Value: 7\r\nCookie: malformed\r\n") == {"value": 7}
