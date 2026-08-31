from __future__ import annotations

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
