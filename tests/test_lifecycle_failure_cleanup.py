from __future__ import annotations

import contextlib
import socket
import threading
from typing import Any

import pytest

from dexpot import Dex


@pytest.mark.parametrize("child", [False, True])
def test_listener_is_closed_if_setup_fails(monkeypatch: pytest.MonkeyPatch, child: bool) -> None:
    import dexpot.app as module

    class Listener:
        closed = False

        def setsockopt(self, *args: Any) -> None:
            pass

        def bind(self, *args: Any) -> None:
            pass

        def listen(self, *args: Any) -> None:
            raise RuntimeError("listener setup failed")

        def close(self) -> None:
            self.closed = True

    listener = Listener()
    monkeypatch.setattr(module.socket, "socket", lambda *args: listener)
    app = Dex()
    with pytest.raises(RuntimeError, match="listener setup failed"):
        if child:
            app._worker_process_serving("127.0.0.1", 0)
        else:
            app._serve_single_process("127.0.0.1", 0)
    assert listener.closed


@pytest.mark.parametrize("child", [False, True])
def test_signal_during_acquisition_unwinds_without_listening(tmp_path, child: bool) -> None:
    import os
    import subprocess
    import sys

    trace = tmp_path / "trace"
    code = f"""
import contextlib, os, signal
from pathlib import Path
from dexpot import Dex
app = Dex()
@contextlib.contextmanager
def resource():
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        yield
    finally:
        Path({str(trace)!r}).write_text('closed')
app.lifespan(resource)
if {child!r}:
    app._compile()
    app._worker_process('127.0.0.1', 0)
else:
    app.serve('127.0.0.1', 0)
"""
    env = os.environ.copy()
    env.pop("DEXPOT_WORKERS", None)
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=8
    )
    assert result.returncode == 0, result.stderr
    assert trace.read_text() == "closed"
    assert "dexpot serving" not in result.stdout


def test_real_held_handler_keeps_resource_until_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    errors: list[BaseException] = []

    @contextlib.contextmanager
    def resource():
        try:
            yield
        finally:
            closed.set()

    app.lifespan(resource)

    @app.get("/held")
    def held():
        entered.set()
        assert release.wait(5)
        assert not closed.is_set()
        return {"ok": True}

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    drain = app._begin_drain
    monkeypatch.setattr(app, "_begin_drain", lambda timeout: drain(timeout=0))

    def serve():
        try:
            app.serve("127.0.0.1", port)
        except BaseException as exc:
            errors.append(exc)

    server = threading.Thread(target=serve)
    server.start()
    conn = None
    try:
        import time

        deadline = time.monotonic() + 3
        while conn is None:
            try:
                conn = socket.create_connection(("127.0.0.1", port), timeout=1)
            except ConnectionRefusedError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        conn.sendall(b"GET /held HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        assert entered.wait(3)
        app._stopping.set()
        server.join(timeout=3)
        assert not server.is_alive()
        assert not errors
        assert not closed.is_set()
        release.set()
        assert closed.wait(3)
    finally:
        release.set()
        app._stopping.set()
        server.join(timeout=3)
        if conn is not None:
            conn.close()


def test_unused_lifecycle_never_enters_completion_bookkeeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dex()
    left, right = socket.socketpair()

    def forbidden() -> None:
        pytest.fail("unused lifecycle entered completion bookkeeping")

    monkeypatch.setattr(app, "_release_deferred_lifecycle", forbidden)
    monkeypatch.setattr(app, "_process", lambda conn, buf: (False, b""))
    try:
        app._own_connection(left, b"")
    finally:
        left.close()
        right.close()


def test_gil_worker_completion_releases_deferred_resources() -> None:
    app = Dex()
    events: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    @contextlib.contextmanager
    def resource():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    app.lifespan(resource)
    left, right = socket.socketpair()

    def process(conn: socket.socket, buf: bytes) -> tuple[bool, bytes]:
        entered.set()
        assert release.wait(3)
        return False, b""

    app._process = process  # type: ignore[method-assign]
    worker = threading.Thread(target=app._worker_gil)
    try:
        with app._acquire_lifecycle():
            with app._cond:
                app._work.append((left, b""))
                app._cond.notify_all()
            worker.start()
            assert entered.wait(3)
            app._begin_drain(timeout=0)
        assert events == ["enter"]
        release.set()
        worker.join(timeout=3)
        assert not worker.is_alive()
        assert events == ["enter", "exit"]
    finally:
        release.set()
        app._stopping.set()
        with app._cond:
            app._cond.notify_all()
        if worker.ident is not None:
            worker.join(timeout=3)
        left.close()
        right.close()
