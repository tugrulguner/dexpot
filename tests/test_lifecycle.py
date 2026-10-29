from __future__ import annotations

import contextlib
import socket

import pytest

from dexpot import Dex


def test_deadline_retains_lifecycle_resources_while_handler_remains_active(monkeypatch) -> None:
    events: list[str] = []
    app = Dex()

    @contextlib.contextmanager
    def resource():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    app.lifespan(resource)
    monkeypatch.setattr(app._lifecycle, "_ensure_finalizer", lambda: None)
    marker = object()
    with app._lifecycle._acquire_lifecycle(), app._cond:
        app._active_connections.add(marker)  # type: ignore[arg-type]
    assert events == ["enter"]
    assert len(app._lifecycle._deferred_lifecycle_stacks) == 1
    with app._cond:
        app._active_connections.remove(marker)  # type: ignore[arg-type]
    app._lifecycle._release_deferred_lifecycle()
    assert events == ["enter", "exit"]


def test_deferred_cleanup_failure_does_not_strand_earlier_resources(monkeypatch) -> None:
    events: list[str] = []
    app = Dex()
    acquisitions = 0

    @contextlib.contextmanager
    def resource():
        nonlocal acquisitions
        acquisitions += 1
        generation = acquisitions
        events.append(f"enter-{generation}")
        try:
            yield
        finally:
            events.append(f"exit-{generation}")
            if generation == 2:
                raise RuntimeError("second cleanup failed")

    app.lifespan(resource)
    monkeypatch.setattr(app._lifecycle, "_ensure_finalizer", lambda: None)
    marker = object()
    with app._cond:
        app._active_connections.add(marker)  # type: ignore[arg-type]
    for _ in range(2):
        with app._lifecycle._acquire_lifecycle():
            pass
    assert events == ["enter-1", "enter-2"]
    assert len(app._lifecycle._deferred_lifecycle_stacks) == 2
    with app._cond:
        app._active_connections.remove(marker)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="second cleanup failed"):
        app._lifecycle._release_deferred_lifecycle()
    assert events == ["enter-1", "enter-2", "exit-2", "exit-1"]
    assert app._lifecycle._deferred_lifecycle_stacks == []
    app._lifecycle._release_deferred_lifecycle()
    assert events == ["enter-1", "enter-2", "exit-2", "exit-1"]


def test_lifecycle_factories_are_frozen_and_cleanup_in_reverse_order() -> None:
    events: list[str] = []
    app = Dex()

    @contextlib.contextmanager
    def first():
        events.append("enter-1")
        yield "one"
        events.append("exit-1")

    @contextlib.contextmanager
    def second():
        events.append("enter-2")
        yield "two"
        events.append("exit-2")

    app.lifespan(first)
    app.lifespan(second)
    app._compile()
    assert events == []

    with app._lifecycle._acquire_lifecycle():
        assert events == ["enter-1", "enter-2"]
    assert events == ["enter-1", "enter-2", "exit-2", "exit-1"]


def test_partial_lifecycle_startup_rolls_back() -> None:
    events: list[str] = []
    app = Dex()

    @contextlib.contextmanager
    def ok():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    @contextlib.contextmanager
    def broken():
        raise RuntimeError("broken acquisition")
        yield

    app.lifespan(ok)
    app.lifespan(broken)
    with (
        pytest.raises(RuntimeError, match="broken acquisition"),
        app._lifecycle._acquire_lifecycle(),
    ):
        pass
    assert events == ["enter", "exit"]


def test_real_server_acquires_before_listening_and_cleans_up_on_sigterm(tmp_path) -> None:
    import os
    import subprocess
    import sys
    import time

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    trace = tmp_path / "trace"
    code = f"""\
import contextlib, pathlib
from dexpot import Dex
trace = pathlib.Path({str(trace)!r})
app = Dex()
@contextlib.contextmanager
def resource():
    trace.write_text("entered")
    try:
        yield
    finally:
        trace.write_text(trace.read_text() + ",exited")
app.lifespan(resource)
@app.get("/health")
def health(): return {{"ok": True}}
app.serve("127.0.0.1", {port})
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    process = subprocess.Popen([sys.executable, "-c", code], env=env)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not trace.exists():
            if process.poll() is not None:
                raise AssertionError("server exited before lifecycle acquisition")
            time.sleep(0.02)
        assert trace.read_text() == "entered"
        with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
            conn.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            assert b"200 OK" in conn.recv(1024)
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert trace.read_text() == "entered,exited"


def test_real_server_initialization_failure_never_binds_listener(tmp_path) -> None:
    import os
    import subprocess
    import sys

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code = f"""\
import contextlib
import socket
from dexpot import Dex
app = Dex()
@contextlib.contextmanager
def broken(): raise RuntimeError("acquisition failure"); yield
app.lifespan(broken)
app.serve("127.0.0.1", {port})
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_multiprocess_acquisition_failure_is_fatal_and_not_retried(tmp_path) -> None:
    import os
    import subprocess
    import sys

    trace = tmp_path / "acquisitions"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code = f"""\
import contextlib, pathlib
from dexpot import Dex
trace = pathlib.Path({str(trace)!r})
app = Dex()
@contextlib.contextmanager
def broken():
    with trace.open("a") as stream: stream.write("attempt\\n")
    raise RuntimeError("acquisition failure")
    yield
app.lifespan(broken)
app.serve("127.0.0.1", {port})
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    env["DEXPOT_WORKERS"] = "2"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert trace.read_text().splitlines() == ["attempt"]
    assert "dexpot serving on" not in result.stdout
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
