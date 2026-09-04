from __future__ import annotations

import builtins
import dis
import inspect
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

import dexpot._plans as plans
import dexpot.app as app_module
from dexpot import Dex


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
