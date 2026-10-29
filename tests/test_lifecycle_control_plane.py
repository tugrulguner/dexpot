from __future__ import annotations

import contextlib
import socket
import threading

import pytest

from dexpot import Dex


def test_registration_and_compile_are_lazy_and_factories_reverse_order() -> None:
    app = Dex()
    events: list[str] = []

    @contextlib.contextmanager
    def resource(name: str):
        events.append("+" + name)
        try:
            yield
        finally:
            events.append("-" + name)

    app.lifespan(lambda: resource("a"))
    app.lifespan(lambda: resource("b"))
    app._compile()
    assert events == []
    with app._lifecycle._acquire_lifecycle():
        assert events == ["+a", "+b"]
    assert events == ["+a", "+b", "-b", "-a"]


def test_partial_acquisition_rolls_back() -> None:
    app = Dex()
    events: list[str] = []

    @contextlib.contextmanager
    def good():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    @contextlib.contextmanager
    def bad():
        raise RuntimeError("failed acquisition")
        yield

    app.lifespan(good)
    app.lifespan(bad)
    with (
        pytest.raises(RuntimeError, match="failed acquisition"),
        app._lifecycle._acquire_lifecycle(),
    ):
        pass
    assert events == ["enter", "exit"]


def test_deferred_stack_is_released_by_final_connection_exit() -> None:
    app = Dex()
    events: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    @contextlib.contextmanager
    def resource():
        try:
            yield
        finally:
            events.append("exit")

    app.lifespan(resource)
    left, right = socket.socketpair()

    def process(_conn: socket.socket, _buf: bytes) -> tuple[bool, bytes]:
        entered.set()
        assert release.wait(3)
        return False, b""

    app._process = process  # type: ignore[method-assign]
    worker = threading.Thread(target=app._own_connection, args=(left, b""))
    try:
        with app._lifecycle._acquire_lifecycle():
            worker.start()
            assert entered.wait(3)
        assert events == []
        finalizer = app._lifecycle._finalizer
        release.set()
        worker.join(3)
        assert finalizer is not None
        finalizer.join(3)
        assert not worker.is_alive()
        assert events == ["exit"]
    finally:
        release.set()
        worker.join(3)
        left.close()
        right.close()


def test_no_lost_completion_when_handler_finishes_before_acquisition_returns() -> None:
    app = Dex()
    events: list[str] = []

    @contextlib.contextmanager
    def resource():
        try:
            yield
        finally:
            events.append("exit")

    app.lifespan(resource)
    left, right = socket.socketpair()
    app._process = lambda _conn, _buf: (False, b"")  # type: ignore[method-assign]
    try:
        with app._lifecycle._acquire_lifecycle():
            app._own_connection(left, b"")
        assert events == ["exit"]
    finally:
        left.close()
        right.close()
