import socket
import subprocess
import sys
import time

import pytest

from dexpot import app as module
from dexpot.app import Dex


@pytest.mark.skipif(module._gil_free, reason="GIL multiprocess worker readiness")
def test_worker_readiness_waits_for_pool_start():
    subprocess.run([sys.executable, __file__, "readiness"], check=True, timeout=20)


def _check_readiness(monkeypatch):
    app = Dex()
    app._compile()
    monkeypatch.setattr(module, "POOL_SIZE", 2)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.settimeout(0.5)
    app._shared_listener = listener
    port = listener.getsockname()[1]
    original = app._start_gil_workers

    def delayed(sock):
        time.sleep(0.2)
        original(sock)

    monkeypatch.setattr(app, "_start_gil_workers", delayed)
    worker = app._new_worker("127.0.0.1", port)
    try:
        ready = getattr(worker, "_dexpot_ready", None)
        assert ready is not None, "worker-ready IPC missing"
        worker.start()
        assert worker.is_alive()
        assert not ready.wait(0.05), "alive process was treated as ready pool"
        assert ready.wait(5)
    finally:
        if worker.pid is not None:
            app._teardown([worker])
        listener.close()


@pytest.mark.skipif(module._gil_free, reason="GIL shared listener lifetime")
def test_worker_closes_only_its_copy_and_replacement_can_accept():
    subprocess.run([sys.executable, __file__, "replacement"], check=True, timeout=25)


def _check_replacement(monkeypatch):
    app = Dex()

    @app.get("/ok")
    def ok():
        return {"ok": True}

    app._compile()
    monkeypatch.setattr(module, "POOL_SIZE", 2)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.settimeout(0.5)
    app._shared_listener = listener
    port = listener.getsockname()[1]
    try:
        for _ in range(2):
            worker = app._new_worker("127.0.0.1", port)
            worker.start()
            try:
                assert worker._dexpot_ready.wait(5)
                with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                    client.sendall(b"GET /ok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
                    data = b""
                    while True:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    assert data.startswith(b"HTTP/1.1 200") and data.endswith(b'{"ok":true}')
            finally:
                app._teardown([worker])
            assert listener.fileno() >= 0 and listener.getsockname()[1] == port
    finally:
        listener.close()


if __name__ == "__main__":
    with pytest.MonkeyPatch.context() as patch:
        {"readiness": _check_readiness, "replacement": _check_replacement}[sys.argv[1]](patch)
