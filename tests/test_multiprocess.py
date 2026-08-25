"""Multiprocess supervisor E2E: run in a real subprocess; assert liveness,
worker count, restart-on-crash, and clean SIGTERM shutdown."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

_is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
_GIL_ENABLED = _is_gil_enabled() if _is_gil_enabled is not None else True


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def mp_server():
    """Start `python tests/worker_app.py <port>` with DEXPOT_WORKERS=2."""
    port = _free_port()
    env = os.environ.copy()
    env["DEXPOT_WORKERS"] = "2"
    env["PYTHONPATH"] = (
        str(Path(__file__).parent.parent / "src") + os.pathsep + env.get("PYTHONPATH", "")
    )
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "worker_app.py"), str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(80):
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            print(f"supervisor exited early: {stderr[-500:]}", file=sys.stderr)
            break
        try:
            httpx.get(f"{base}/health", timeout=0.5)
            ready = True
            break
        except httpx.HTTPError:
            time.sleep(0.25)
    yield proc, port, ready
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_multiprocess_liveness_and_shutdown(mp_server):
    proc, port, ready = mp_server
    assert ready, "supervisor did not become ready"

    # liveness across workers (kernel reuseport balances between them)
    for _ in range(10):
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
        assert r.status_code == 200

    # graceful shutdown on SIGTERM within the grace window
    proc.send_signal(signal.SIGTERM)
    rc = proc.wait(timeout=12)
    assert rc == 0, f"supervisor exited {rc} instead of clean 0"

    # listener is actually closed after shutdown
    s = socket.socket()
    s.settimeout(1)
    with pytest.raises(OSError):
        s.connect(("127.0.0.1", port))
    s.close()


@pytest.mark.skipif(not _GIL_ENABLED, reason="free-threaded mode intentionally uses one process")
def test_multiprocess_restarts_crashed_worker(mp_server):
    proc, port, ready = mp_server
    assert ready

    children = [int(p) for p in proc_pids(proc.pid)]
    assert len(children) >= 2, f"expected >=2 workers, found {children}"

    # kill one worker directly; the supervisor must respawn it
    os.kill(children[0], signal.SIGKILL)

    # Poll rather than sleep once: CI scheduling can delay the 1s supervisor scan.
    new_children: set[int] = set()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        new_children = {int(p) for p in proc_pids(proc.pid)}
        if len(new_children) >= 2 and children[0] not in new_children:
            break
        time.sleep(0.25)

    if proc.poll() is not None:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        pytest.fail(
            "supervisor exited after a worker crash:\n"
            f"stdout={stdout[-1000:]}\nstderr={stderr[-2000:]}"
        )
    assert len(new_children) >= 2, "supervisor did not restore worker count"
    assert children[0] not in new_children, "killed worker PID was not replaced"
    assert httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200


def proc_pids(parent_pid: int) -> set[str]:
    out = subprocess.run(
        ["pgrep", "-P", str(parent_pid)], capture_output=True, text=True, check=False
    )
    return {line for line in out.stdout.split() if line}
