from __future__ import annotations

import builtins
import dis
import gc
import inspect
import socket
import threading
import time
from dataclasses import FrozenInstanceError

import msgspec
import pytest

import dexpot._plans as plans
import dexpot.app as app_module
from dexpot import Dex, Request


def test_application_compiles_once_into_an_immutable_plan() -> None:
    app = Dex()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    first = app._compile()
    second = app._compile()

    assert first is second
    assert first.router.match("GET", "/health")[0] is not None
    with pytest.raises(FrozenInstanceError):
        first.router = first.router  # type: ignore[misc]


def test_compiled_endpoint_is_immutable() -> None:
    app = Dex()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    endpoint, _captures, _allowed = app._compile().router.match("GET", "/health")

    assert endpoint is not None
    with pytest.raises(FrozenInstanceError):
        endpoint.summary = "changed"  # type: ignore[attr-defined]


def test_application_plan_retains_endpoint_contracts() -> None:
    app = Dex()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/users/{user_id}")
    def create_user(user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    plan = app._compile()

    assert [(endpoint.method, endpoint.path) for endpoint in plan.endpoints] == [
        ("GET", "/health"),
        ("POST", "/users/{user_id}"),
    ]


def test_endpoint_precompiles_direct_invoker_for_supported_shapes() -> None:
    app = Dex()
    default_marker = object()

    @app.post("/parents/{parent_id}/children/{child_id}", body=dict[str, str])
    def create_child(
        child_id: int,
        /,
        payload: dict[str, str],
        marker: object = default_marker,
        *,
        parent_id: int,
        enabled: bool = True,
    ) -> tuple[int, dict[str, str], object, int, bool]:
        return child_id, payload, marker, parent_id, enabled

    endpoint = app._compile().endpoints[0]

    assert endpoint.invoke([11, 22], {"tag": "compiled"}) == (
        22,
        {"tag": "compiled"},
        default_marker,
        11,
        True,
    )


def test_request_is_frozen_gc_tracked_public_context() -> None:
    minimal = Request("GET", "/", {}, "", {})
    validated = object()
    request = Request(
        "GET",
        "/items/7",
        {"item_id": "7"},
        "expanded=true",
        {"host": "example.test"},
        b"",
        validated,
    )

    assert minimal.raw_body == b""
    assert minimal.body is None
    assert isinstance(request, msgspec.Struct)
    assert gc.is_tracked(request)
    assert request.raw_body == b""
    assert request.body is validated
    with pytest.raises(AttributeError, match="immutable"):
        request.method = "POST"  # type: ignore[misc]


def test_endpoint_injects_request_by_annotation_through_direct_invoker() -> None:
    app = Dex()

    @app.post("/items/{item_id}", body=dict[str, str])
    def create_item(
        payload: dict[str, str], /, *, request: Request, item_id: int
    ) -> tuple[object, int, dict[str, str]]:
        return request, item_id, payload

    endpoint = app._compile().endpoints[0]
    request = Request("POST", "/items/7", {"item_id": "7"}, "", {}, b"{}")
    payload = {"name": "compiled"}
    opnames = {instruction.opname for instruction in dis.get_instructions(endpoint.invoke)}

    assert endpoint.needs_request is True
    assert endpoint.invoke([7], payload, request) == (request, 7, payload)
    assert "BUILD_LIST" not in opnames
    assert "BUILD_MAP" not in opnames
    assert "CALL_FUNCTION_EX" not in opnames
    assert "LOAD_GLOBAL" not in opnames


def test_unannotated_request_name_remains_an_ordinary_default() -> None:
    app = Dex()

    @app.get("/default")
    def default(request: object = None) -> object:
        return request

    endpoint = app._compile().endpoints[0]
    assert endpoint.needs_request is False
    assert endpoint.invoke([], None) is None


def test_request_annotation_is_not_inferred_as_a_json_body() -> None:
    app = Dex()

    @app.post("/request")
    def inspect_request(request: Request) -> str:
        return request.method

    endpoint = app._compile().endpoints[0]

    assert endpoint.body_decoder is None
    assert endpoint.needs_request is True


def test_postponed_local_request_alias_is_resolved_during_registration() -> None:
    def build() -> Dex:
        from dexpot import Request as LocalRequest

        app = Dex()

        @app.get("/local-request", annotation_locals={"LocalRequest": LocalRequest})
        def inspect_request(request: LocalRequest) -> str:
            return request.method

        return app

    endpoint = build()._compile().endpoints[0]
    request = Request("GET", "/local-request", {}, "", {})

    assert endpoint.needs_request is True
    assert endpoint.invoke([], None, request) == "GET"


def test_wrapped_factory_handler_resolves_local_request_alias() -> None:
    from functools import wraps

    def passthrough(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    def build() -> Dex:
        from dexpot import Request as Alias

        app = Dex()

        @app.get("/wrapped", annotation_locals={"Alias": Alias})
        @passthrough
        def handler(request: Alias) -> str:
            return request.method

        return app

    endpoint = build()._compile().endpoints[0]
    assert endpoint.invoke([], None, Request("GET", "/wrapped", {}, "", {})) == "GET"


def test_registration_locals_do_not_override_existing_handler_scope() -> None:
    def handler(request: Request, item_id: int) -> tuple[str, int]:
        return request.method, item_id

    def register() -> Dex:
        Request = str
        int = str
        assert Request is int  # Unrelated registration-site names, not annotations.
        app = Dex()
        app.get("/items/{item_id}")(handler)
        return app

    endpoint = register()._compile().endpoints[0]
    assert endpoint.needs_request
    assert endpoint.int_captures == ((0, "item_id"),)
    request = Request("GET", "/items/7", {}, "", {})
    assert endpoint.invoke([7], None, request) == ("GET", 7)


def test_request_defaults_and_parameter_kinds_receive_the_same_context() -> None:
    app = Dex()

    @app.get("/request-kinds")
    def inspect_request(
        request: Request = None,  # type: ignore[assignment]
        /,
        *,
        second: Request = None,  # type: ignore[assignment]
    ) -> tuple[Request, Request]:
        return request, second

    endpoint = app._compile().endpoints[0]
    context = Request("GET", "/request-kinds", {}, "", {})

    assert endpoint.invoke([], None, context) == (context, context)


def test_request_and_inferred_payload_select_the_payload_body_type() -> None:
    app = Dex()

    class Payload(msgspec.Struct):
        value: int

    def handler(request: Request, payload: Payload) -> int:
        return request.body.value + payload.value

    handler.__annotations__ = {"request": Request, "payload": Payload, "return": int}
    app.post("/inferred")(handler)

    endpoint = app._compile().endpoints[0]

    assert endpoint.body_type is Payload
    assert endpoint.needs_request is True
    payload = endpoint.body_decoder.decode(b'{"value": 7}')
    request = Request("POST", "/inferred", {}, "", {}, b'{"value": 7}', payload)
    assert endpoint.invoke([], payload, request) == 14


def test_request_rejects_conflicting_path_and_body_declarations() -> None:
    app = Dex()

    with pytest.raises(TypeError, match="cannot also be annotated as Request"):

        @app.get("/items/{request}")
        def conflicting_path(request: Request) -> str:
            return request.path

    with pytest.raises(TypeError, match="cannot be used as a body type"):

        @app.post("/body-request", body=Request)
        def conflicting_body(request: Request) -> str:
            return request.path


def test_requestless_processing_does_not_construct_public_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app._compile()

    def fail_request(*args: object, **kwargs: object) -> Request:
        raise AssertionError("requestless route constructed public Request")

    monkeypatch.setattr(app_module, "Request", fail_request)
    client, server = socket.socketpair()
    try:
        client.sendall(b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        keep_alive, remaining = app._process(server, b"")
        response = client.recv(4096)
    finally:
        client.close()
        server.close()

    assert keep_alive is False
    assert remaining == b""
    assert response.startswith(b"HTTP/1.1 200")


def test_request_is_constructed_once_only_after_body_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()

    class Payload(msgspec.Struct):
        value: int

    @app.post("/context", body=Payload)
    def context(payload: Payload, request: Request) -> dict[str, bool]:
        return {"same_body": request.body is payload}

    app._compile()
    original_request = app_module.Request
    calls = 0

    def count_request(
        method: str,
        path: str,
        params: dict[str, str],
        query: str,
        headers: dict[str, str],
        raw_body: bytes = b"",
        body: object = None,
    ) -> Request:
        nonlocal calls
        calls += 1
        return original_request(method, path, params, query, headers, raw_body, body)

    def process(body: bytes) -> bytes:
        client, server = socket.socketpair()
        try:
            client.sendall(
                b"POST /context HTTP/1.1\r\nHost: test\r\nConnection: close\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            app._process(server, b"")
            return client.recv(4096)
        finally:
            client.close()
            server.close()

    monkeypatch.setattr(app_module, "Request", count_request)

    assert process(b'{"value":"invalid"}').startswith(b"HTTP/1.1 422")
    assert calls == 0
    assert process(b'{"value":7}').startswith(b"HTTP/1.1 200")
    assert calls == 1


def test_endpoint_invoker_avoids_generic_argument_containers() -> None:
    app = Dex()

    @app.get("/items/{item_id}")
    def item(*, item_id: int) -> int:
        return item_id

    endpoint = app._compile().endpoints[0]
    opnames = {instruction.opname for instruction in dis.get_instructions(endpoint.invoke)}

    assert endpoint.invoke([7], None) == 7
    assert "BUILD_LIST" not in opnames
    assert "BUILD_MAP" not in opnames
    assert "CALL_FUNCTION_EX" not in opnames
    assert "LOAD_GLOBAL" not in opnames


def test_endpoint_invoker_preserves_non_normalized_keyword_names() -> None:
    app = Dex()

    def handler(**kwargs: int) -> dict[str, int]:
        return kwargs

    fullwidth_x = "\uff58"
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter(fullwidth_x, inspect.Parameter.KEYWORD_ONLY, annotation=int)]
    )
    app.get(f"/items/{{{fullwidth_x}}}")(handler)

    endpoint = app._compile().endpoints[0]

    assert endpoint.invoke([7], None) == {fullwidth_x: 7}


def test_endpoints_with_the_same_call_shape_share_compiled_code() -> None:
    app = Dex()

    @app.get("/first")
    def first() -> int:
        return 1

    @app.get("/second")
    def second() -> int:
        return 2

    first_endpoint, second_endpoint = app._compile().endpoints

    assert first_endpoint.invoke.__code__ is second_endpoint.invoke.__code__
    assert first_endpoint.invoke.__globals__ is second_endpoint.invoke.__globals__
    assert first_endpoint.invoke.__globals__ == {}
    assert first_endpoint.invoke([], None) == 1
    assert second_endpoint.invoke([], None) == 2


def test_concurrent_cold_misses_share_one_compiled_code(monkeypatch: pytest.MonkeyPatch) -> None:
    real_compile = builtins.compile
    compile_calls = 0
    count_lock = threading.Lock()

    def slow_invoker_compile(*args: object, **kwargs: object):
        nonlocal compile_calls
        if len(args) > 1 and args[1] == "<dexpot-endpoint-invoker>":
            with count_lock:
                compile_calls += 1
            time.sleep(0.05)
        return real_compile(*args, **kwargs)  # type: ignore[call-overload]

    plans._invoker_code.cache_clear()
    monkeypatch.setattr(builtins, "compile", slow_invoker_compile)
    invokers = []

    def compile_endpoint() -> None:
        app = Dex()

        @app.get("/health")
        def health() -> int:
            return 1

        invokers.append(app._compile().endpoints[0].invoke)

    threads = [threading.Thread(target=compile_endpoint) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert compile_calls == 1
    assert len({id(invoker.__code__) for invoker in invokers}) == 1


def test_router_precompiles_parameter_segments() -> None:
    app = Dex()

    @app.get("/users/{user_id}")
    def user(user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    route = app._compile().router.parametric_by_length[2][0]

    assert route.segments == ("users", None)


def test_registration_fails_after_application_compilation() -> None:
    app = Dex()

    @app.get("/before")
    def before() -> dict[str, bool]:
        return {"before": True}

    app._compile()

    with pytest.raises(RuntimeError, match="application is compiled"):

        @app.get("/after")
        def after() -> dict[str, bool]:
            return {"after": True}


def test_compilation_waits_for_registration_already_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()
    registration_entered = threading.Event()
    release_registration = threading.Event()
    compilation_finished = threading.Event()
    errors: list[BaseException] = []
    real_endpoint_plan = app_module.EndpointPlan

    def blocking_endpoint_plan(*args: object, **kwargs: object) -> object:
        registration_entered.set()
        if not release_registration.wait(timeout=2):
            raise TimeoutError("registration was not released")
        return real_endpoint_plan(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(app_module, "EndpointPlan", blocking_endpoint_plan)

    def register() -> None:
        try:

            @app.get("/late")
            def late() -> dict[str, bool]:
                return {"late": True}
        except BaseException as exc:
            errors.append(exc)

    compiled: list[object] = []

    def compile_app() -> None:
        try:
            compiled.append(app._compile())
        except BaseException as exc:
            errors.append(exc)
        finally:
            compilation_finished.set()

    registration_thread = threading.Thread(target=register)
    compilation_thread = threading.Thread(target=compile_app)
    registration_thread.start()
    assert registration_entered.wait(timeout=2)
    compilation_thread.start()

    assert not compilation_finished.wait(timeout=0.05)
    release_registration.set()
    registration_thread.join(timeout=2)
    compilation_thread.join(timeout=2)

    assert not registration_thread.is_alive()
    assert not compilation_thread.is_alive()
    assert errors == []
    assert [endpoint.path for endpoint in compiled[0].endpoints] == ["/late"]  # type: ignore[attr-defined]


def test_reentrant_compilation_during_annotation_resolution_cannot_publish_partial_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()
    compilation_attempts: list[bool] = []

    def freeze_during_annotation() -> type[int]:
        compilation_attempts.append(True)
        app._compile()
        return int

    monkeypatch.setitem(globals(), "freeze_during_annotation", freeze_during_annotation)

    with pytest.raises(RuntimeError, match="route registration is in progress"):

        @app.get("/items/{item_id}")
        def item(item_id: freeze_during_annotation()) -> dict[str, int]:  # type: ignore[name-defined]
            return {"item_id": item_id}

    assert compilation_attempts == [True]
    assert app._endpoints == []
    assert app._literal == {}
    assert app._parametric == []
    assert app._plan is None


def test_serve_compiles_before_opening_a_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    app = Dex()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    class ListenerReached(Exception):
        pass

    def listener(*_args: object) -> None:
        assert app._plan is not None
        raise ListenerReached

    monkeypatch.setattr(app_module.socket, "socket", listener)

    with pytest.raises(ListenerReached):
        app.serve()
