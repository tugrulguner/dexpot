import select
import socket
import threading

import pytest

from dexpot import app as module
from dexpot.app import Dex


@pytest.mark.skipif(module._gil_free, reason="GIL hot-connection handoff")
def test_hot_connection_retains_short_gap_when_no_peer_waits(monkeypatch):
    app = Dex()
    app._compile()
    hub = app._ensure_gil_hub()
    server, client = socket.socketpair()
    calls = []

    def process(conn, buf):
        calls.append("process")
        if len(calls) == 2:
            app._stopping.set()
            return False, b""
        return True, b""

    def ready(read, write, error, timeout):
        # Deterministic peer arrival 2ms after the response, not a host timer test.
        return (read, [], []) if timeout >= 0.002 else ([], [], [])

    def park(conn, buf, *, deadline=None):
        calls.append("park")
        app._stopping.set()
        hub.release(conn)

    monkeypatch.setattr(app, "_process", process)
    monkeypatch.setattr(select, "select", ready)
    monkeypatch.setattr(hub, "park", park)
    with app._cond:
        app._work.append((server, b""))
    worker = threading.Thread(target=app._worker_gil)
    worker.start()
    worker.join(2)
    try:
        assert calls == ["process", "process"]
        assert not worker.is_alive()
    finally:
        app._begin_drain(0)
        worker.join(2)
        server.close()
        client.close()


@pytest.mark.skipif(module._gil_free, reason="GIL hot-connection fairness")
def test_queued_peer_preempts_hot_connection_wait(monkeypatch):
    app = Dex()
    app._compile()
    app._ensure_gil_hub()
    first, peer = socket.socketpair()
    second, other = socket.socketpair()
    calls = []

    def process(conn, buf):
        if conn is first:
            calls.append("first")
            return True, b""
        calls.append("second")
        app._stopping.set()
        return False, b""

    def ready(*args):
        calls.append("wait")
        return [], [], []

    monkeypatch.setattr(app, "_process", process)
    monkeypatch.setattr(select, "select", ready)
    with app._cond:
        app._work.extend([(first, b""), (second, b"")])
    worker = threading.Thread(target=app._worker_gil)
    worker.start()
    worker.join(2)
    try:
        assert calls == ["first", "second"]
        assert not worker.is_alive()
    finally:
        app._begin_drain(0)
        worker.join(2)
        for conn in [first, peer, second, other]:
            conn.close()
