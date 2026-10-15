import contextlib
import socket
import threading
import time

import pytest

from dexpot import app as module
from dexpot._http import HttpLimits


@pytest.mark.skipif(module._gil_free, reason="GIL keepalive deadline")
def test_grace_and_reactor_share_one_idle_expiry():
    results = []
    for _ in range(10):
        app = module.Dex(limits=HttpLimits(idle_read_seconds=0.004, head_read_seconds=1))

        @app.get("/ok")
        def ok():
            return {"ok": True}

        app._compile()
        worker = threading.Thread(target=app._worker_gil)
        worker.start()
        server, client = socket.socketpair()
        client.settimeout(1)
        app._handle_admission(server, b"GET /ok HTTP/1.1\r\nHost: x\r\n\r\n")

        def response(conn=client):
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                assert chunk, "unexpected EOF"
                data += chunk
            head, body = data.split(b"\r\n\r\n", 1)
            length = int(
                next(
                    line.split(b":", 1)[1]
                    for line in head.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
            )
            while len(body) < length:
                chunk = conn.recv(4096)
                assert chunk, "unexpected EOF"
                body += chunk
            return head.split(b"\r\n")[0].decode()

        try:
            assert "200" in response()
            time.sleep(0.006)
            with contextlib.suppress(BrokenPipeError):
                client.sendall(b"GET /ok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            results.append(response())
        finally:
            client.close()
            app._begin_drain(0)
            worker.join(1)
            assert not worker.is_alive()
    assert all("408" in value for value in results), results
