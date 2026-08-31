from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError

import pytest

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
