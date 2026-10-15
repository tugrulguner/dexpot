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
