"""Ordinary keep-alive connections cannot all be captured by one fast acceptor."""

import concurrent.futures
import http.client
import json
import multiprocessing
import os
import select
import signal
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

GIL = getattr(sys, "_is_gil_enabled", lambda: True)()
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process supervisor")
def test_started_worker_is_owned_before_control_peer_cleanup(monkeypatch):
    from dexpot import Dex
    from dexpot._gil_accept import GILAcceptTurns

    app = Dex()
    worker = SimpleNamespace(alive=False)
    worker.start = lambda: setattr(worker, "alive", True)
    monkeypatch.setattr(app, "_new_worker", lambda *args, **kwargs: worker)
    monkeypatch.setattr(
        app, "_teardown", lambda processes: [setattr(p, "alive", False) for p in processes]
    )

    def fail_peer_close(self, slot):
        raise RuntimeError("control peer cleanup failed")

    monkeypatch.setattr(GILAcceptTurns, "parent_started", fail_peer_close)
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with pytest.raises(RuntimeError, match="control peer cleanup failed"):
            app._serve_multiprocess("127.0.0.1", 0, 2)
        assert not worker.alive, "a started worker escaped supervisor cleanup"
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_unresponsive_live_worker_does_not_hold_all_connection_turns(monkeypatch):
    from dexpot import _gil_accept as module

    coordinator = module.GILAcceptTurns(multiprocessing.get_context(), 2)
    peers = [coordinator.new_channel(i) for i in range(2)]
    processes = [
        SimpleNamespace(is_alive=lambda: True, _dexpot_ready=SimpleNamespace(is_set=lambda: True))
        for _ in range(2)
    ]
    now = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0], raising=False)
    try:
        coordinator.step(processes)
        assert peers[0].recv_bytes() == b"A"
        # Worker zero is alive but does not acknowledge. Its outstanding grant
        # remains bounded while a healthy peer must still receive new work.
        now[0] += 2
        coordinator.step(processes)
        coordinator.step(processes)
        assert peers[1].poll(0.1), "one unresponsive worker stalled every acceptor"
        assert peers[1].recv_bytes() == b"A"
    finally:
        coordinator.close()


@pytest.mark.skipif(os.name != "posix" or not GIL, reason="POSIX GIL multiprocess serving")
def test_fast_worker_yields_next_accept_to_ready_peer(tmp_path):
    release = tmp_path / "release-peer"
    script = tmp_path / "app.py"
    script.write_text("""import multiprocessing, os, socket, sys, time
from pathlib import Path
from dexpot import Dex
app = Dex()
favored = multiprocessing.get_context("fork").Value("i", 0)
original_new = app._new_worker
def new_worker(*args, **kwargs):
    process = original_new(*args, **kwargs)
    original_start = process.start
    def start():
        original_start()
        if favored.value == 0:
            favored.value = process.pid
    process.start = start
    return process
app._new_worker = new_worker
original_accept = socket.socket.accept
def delayed_peer(listener):
    if os.getpid() != favored.value:
        while not Path(sys.argv[2]).exists() and not app._stopping.is_set():
            time.sleep(0.005)
    return original_accept(listener)
socket.socket.accept = delayed_peer
@app.get("/worker")
def worker():
    return {"pid": os.getpid()}
app.serve("127.0.0.1", int(sys.argv[1]))
""")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "DEXPOT_WORKERS": "4", "DEXPOT_POOL": "2"}
    process = subprocess.Popen(
        [sys.executable, str(script), str(port), str(release)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    clients = [http.client.HTTPConnection("127.0.0.1", port, timeout=5) for _ in range(2)]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def get_worker(client):
        client.request("GET", "/worker")
        response = client.getresponse()
        assert response.status == 200
        return json.loads(response.read())["pid"]

    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 8)[0], "server did not announce readiness"
        assert b"mode=pooled-gil(2)x4" in process.stdout.readline()
        first = get_worker(clients[0])
        next_request = pool.submit(get_worker, clients[1])
        # Peers are deliberately held before accept(). The favored worker must
        # not steal their turns, even though it could accept immediately.
        with pytest.raises(concurrent.futures.TimeoutError):
            next_request.result(timeout=0.15)
        release.touch()
        assert next_request.result(timeout=3) != first
    finally:
        release.touch(exist_ok=True)
        pool.shutdown(wait=True)
        for client in clients:
            client.close()
        process.send_signal(signal.SIGTERM)
        try:
            process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=2)
