"""Harness teardown must contain even an uncooperative owned descendant."""

import contextlib
import os
import runpy
import signal
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def alive(pid):
    # A Linux container's PID1 may retain an orphan zombie; it cannot execute or hold sockets.
    stat = Path(f"/proc/{pid}/stat")
    try:
        if stat.exists() and stat.read_text().rsplit(") ", 1)[1].split()[0] == "Z":
            return False
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False


@pytest.mark.skipif(os.name != "posix", reason="the measurement runner uses POSIX process groups")
def test_server_teardown_terminates_its_owned_descendant_and_reports_forcing(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(ROOT / "benchmarks/regression/run.py"))
    original = ROOT / "benchmarks/regression/application.py"
    pidfile = tmp_path / "child.pid"
    child = (
        "import os,signal,time;from pathlib import Path;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)"
    )
    (tmp_path / "application.py").write_text(
        "import runpy,subprocess,sys\n"
        f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
        f"runpy.run_path({str(original)!r},run_name='__main__')\n"
    )
    manager = namespace["server"]
    monkeypatch.setitem(manager.__wrapped__.__globals__, "ROOT", tmp_path)
    env = dict(os.environ, DEXPOT_WORKERS="1", DEXPOT_HTTP_PARSER="python")
    pid = None
    try:
        with manager(sys.executable, env, tmp_path / "server.log") as (_, _, state):
            deadline = time.monotonic() + 3
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            pid = int(pidfile.read_text())
            assert alive(pid)
        deadline = time.monotonic() + 3
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not alive(pid), "owned descendant survived server teardown"
        assert state["cleanup_pass"] is False, "forced cleanup is not a clean lifecycle pass"
    finally:
        if pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
