import socket
import threading

from dexpot import app as module
from dexpot.app import Dex


def test_idle_deadline_storage_and_execution_count_stay_bounded(monkeypatch):
    monkeypatch.setattr(module, "POOL_SIZE", 2)
    monkeypatch.setattr(module, "MAX_CONNECTIONS", 8)
    app = Dex()

    @app.get("/ok")
    def ok():
        return {"ok": True}

    app._compile()
    hub = app._ensure_gil_hub()
    workers = [threading.Thread(target=app._worker_gil) for _ in range(2)]
    for worker in workers:
        worker.start()
    pairs = []
    try:
        assert hasattr(hub, "deadlines")
        for _ in range(8):
            server, client = socket.socketpair()
            client.settimeout(2)
            assert hub.admit(server, b"")
            pairs.append((server, client))
        for _ in range(8):
            for _, client in pairs:
                client.sendall(b"GET /ok HTTP/1.1\r\nHost: x\r\n\r\n")
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = client.recv(4096)
                    assert chunk, "EOF before complete response"
                    data += chunk
                head, body = data.split(b"\r\n\r\n", 1)
                assert head.startswith(b"HTTP/1.1 200")
                length = int(
                    next(
                        line.split(b":", 1)[1]
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                )
                while len(body) < length:
                    chunk = client.recv(4096)
                    assert chunk
                    body += chunk
                assert body == b'{"ok":true}'
                with hub.lock:
                    assert len(hub.states) <= 8
                    assert len(hub.commands) <= len(hub.states)
                    assert len(hub.deadlines) <= 3 * 8
                    assert hub.outstanding == sum(
                        state in ("ready", "queued", "active") for state in hub.states.values()
                    )
    finally:
        for _, client in pairs:
            client.close()
        app._begin_drain(timeout=1)
        for worker in workers:
            worker.join(timeout=2)
    assert not hub.thread.is_alive()
    assert all(not worker.is_alive() for worker in workers)
    assert not hub.states and hub.outstanding == 0
