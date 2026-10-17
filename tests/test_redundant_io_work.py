"""Avoid syscall and wakeup work that does not change connection state."""

import socket
import sys
import threading

import pytest

from dexpot import Dex
from dexpot._http import HttpLimits, read_request


@pytest.mark.parametrize(("initial_timeout", "expected_sets"), [(0.5, 0), (1.0, 1)])
def test_unchanged_socket_timeout_is_not_reset(initial_timeout, expected_sets):
    server, client = socket.socketpair()
    server.settimeout(initial_timeout)
    client.sendall(b"GET / HTTP/1.1\r\nHost: test\r\n\r\n")
    calls = []
    previous = sys.getprofile()

    def profile(frame, event, value):
        if (
            event == "c_call"
            and getattr(value, "__name__", None) == "settimeout"
            and getattr(value, "__self__", None) is server
        ):
            calls.append(True)

    try:
        sys.setprofile(profile)
        request, rest = read_request(
            server, b"", HttpLimits(idle_read_seconds=0.5, head_read_seconds=2)
        )
        sys.setprofile(previous)
        assert request.path == "/"
        assert rest == b""
        assert server.gettimeout() == 0.5
        assert len(calls) == expected_sets
    finally:
        sys.setprofile(previous)
        server.close()
        client.close()


@pytest.mark.parametrize("stop_in_handler", [False, True])
def test_worker_completion_notifies_all_only_during_shutdown(monkeypatch, stop_in_handler):
    class ObservedCondition(threading.Condition):
        broadcasts = 0

        def notify_all(self):
            self.broadcasts += 1
            return super().notify_all()

    app = Dex()
    condition = ObservedCondition()
    app._cond = condition

    @app.get("/")
    def handler():
        if stop_in_handler:
            app._stopping.set()
        return {"ok": True}

    app._compile()
    hub = app._ensure_gil_hub()
    server, client = socket.socketpair()
    server.settimeout(0.5)
    client.settimeout(0.5)
    client.sendall(b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
    observed = []
    release = hub.release

    def record_release(conn):
        observed.append(condition.broadcasts)
        app._stopping.set()
        release(conn)

    monkeypatch.setattr(hub, "release", record_release)
    app._work.append((server, b"", None))
    try:
        app._worker_gil()
        # One startup readiness broadcast; only shutdown adds a completion broadcast.
        assert observed == [2 if stop_in_handler else 1]
        assert not app._active_connections
        assert client.recv(4096).startswith(b"HTTP/1.1 200 OK")
    finally:
        app._stopping.set()
        hub.stop()
        server.close()
        client.close()
