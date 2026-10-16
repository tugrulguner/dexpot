from __future__ import annotations

import socket
import threading
import time

import pytest

from dexpot import app as app_module
from dexpot._http import HttpLimits
from dexpot.app import Dex


def _read_response(sock: socket.socket) -> bytes:
    sock.settimeout(2)
    data = bytearray()
    while b"\r\n\r\n" not in data:
        data.extend(sock.recv(4096))
    headers, body = bytes(data).split(b"\r\n\r\n", 1)
    length = int(
        next(
            line.split(b":", 1)[1]
            for line in headers.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
    )
    while len(body) < length:
        body += sock.recv(4096)
    return headers + b"\r\n\r\n" + body[:length]


def test_idle_keepalive_does_not_occupy_workers_and_pipeline_is_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "POOL_SIZE", 2)
    app = Dex(limits=HttpLimits(idle_read_seconds=0.25))

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    app._compile()
    workers = [threading.Thread(target=app._worker_gil) for _ in range(2)]
    for worker in workers:
        worker.start()
    idle = []
    try:
        for _ in range(8):
            server, client = socket.socketpair()
            idle.append((server, client))
            server.settimeout(0.25)
            app._handle_admission(server, b"")
        time.sleep(0.05)
        server, client = socket.socketpair()
        client.settimeout(2)
        try:
            app._handle_admission(
                server, b"GET /ok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
            )
            response = _read_response(client)
            assert response.startswith(b"HTTP/1.1 200")
            assert b'{"ok":true}' in response
        finally:
            client.close()
    finally:
        for _server, client in idle:
            client.close()
        app._begin_drain(timeout=1)
        for worker in workers:
            worker.join(timeout=2)
    assert all(not worker.is_alive() for worker in workers)


@pytest.mark.skipif(app_module._gil_free, reason="GIL readiness queue")
@pytest.mark.parametrize("expired", [False, True])
def test_ready_queue_preserves_head_budget(expired: bool) -> None:
    app = Dex(limits=HttpLimits(idle_read_seconds=1.0, head_read_seconds=0.2))
    invoked = []

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        invoked.append(True)
        return {"ok": True}

    app._compile()
    hub = app._ensure_gil_hub()
    server, client = socket.socketpair()
    worker = threading.Thread(target=app._worker_gil)
    started = False
    try:
        assert hub.admit(server, b"")
        client.sendall(b"GET /ok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        deadline = time.monotonic() + 2
        while True:
            with hub.lock:
                if hub.states.get(server) == "queued":
                    break
            assert time.monotonic() < deadline, "request did not enter the worker queue"
            time.sleep(0.001)
        if expired:
            time.sleep(0.25)
        worker.start()
        started = True
        response = _read_response(client)
        assert response.startswith(b"HTTP/1.1 408" if expired else b"HTTP/1.1 200")
        assert invoked == ([] if expired else [True])
    finally:
        client.close()
        app._begin_drain(timeout=0)
        if started:
            worker.join(timeout=2)
            assert not worker.is_alive()
