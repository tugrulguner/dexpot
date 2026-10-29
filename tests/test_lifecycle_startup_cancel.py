from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.name != "posix"
    or not hasattr(socket, "SO_REUSEPORT")
    or not getattr(sys, "_is_gil_enabled", lambda: True)(),
    reason="GIL multiprocess lifecycle startup requires POSIX SO_REUSEPORT",
)
@pytest.mark.parametrize("recipient", ["child", "supervisor"])
def test_sigterm_during_worker_acquisition_is_clean_stop(tmp_path, recipient) -> None:
    trace = tmp_path / "acquisitions"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code = f"""
import contextlib, multiprocessing, os, signal, socket
from pathlib import Path
from dexpot import Dex
trace = Path({str(trace)!r})
app = Dex()
def original(*args): pass
signal.signal(signal.SIGTERM, original)
signal.signal(signal.SIGINT, original)
def record(kind):
    with trace.open('a') as stream:
        stream.write(kind + ':' + str(os.getpid()) + '\\n')
@contextlib.contextmanager
def resource():
    record('enter')
    try:
        if {recipient!r} == 'child':
            os.kill(os.getpid(), signal.SIGTERM)
        else:
            os.kill(os.getppid(), signal.SIGTERM)
            assert app._stopping.wait(10), 'supervisor never stopped its acquiring child'
        yield
    finally:
        record('exit')
app.lifespan(resource)
app.serve('127.0.0.1', {port})
assert signal.getsignal(signal.SIGTERM) is original
assert signal.getsignal(signal.SIGINT) is original
assert not multiprocessing.active_children(), 'started worker escaped supervisor ownership'
with socket.socket() as probe:
    probe.bind(('127.0.0.1', {port}))
print('startup cancelled cleanly', flush=True)
"""
    env = dict(os.environ, DEXPOT_WORKERS="2")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "startup cancelled cleanly" in result.stdout
    assert "dexpot serving on" not in result.stdout
    records = trace.read_text().splitlines()
    assert len(records) == 2, "cancelled initialization was retried or not unwound"
    assert records[0].startswith("enter:")
    assert records[1] == records[0].replace("enter:", "exit:", 1)
