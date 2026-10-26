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


@pytest.mark.parametrize("deny_first_probe", [False, True])
def test_group_probe_denial_remains_failed_cleanup_without_losing_result(
    tmp_path, monkeypatch, deny_first_probe
):
    import itertools

    namespace = runpy.run_path(str(ROOT / "benchmarks/regression/run.py"))
    manager = namespace["server"]
    scope = manager.__wrapped__.__globals__

    class Process:
        pid = 12345
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(scope["subprocess"], "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setitem(scope, "request", lambda *args: (200, b"{}"))
    clock = itertools.count()
    monkeypatch.setattr(scope["time"], "monotonic", lambda: next(clock))
    monkeypatch.setattr(scope["time"], "sleep", lambda seconds: None)
    probes = 0
    signals = []

    def killpg(pid, sig):
        nonlocal probes
        assert pid == Process.pid
        signals.append(sig)
        if sig == 0:
            probes += 1
            if deny_first_probe or probes > 1:
                raise PermissionError("group liveness unknown after forced cleanup")

    monkeypatch.setattr(scope["os"], "killpg", killpg)
    with manager(sys.executable, {}, tmp_path / "server.log") as (_, _, state):
        pass
    assert (signal.SIGKILL in signals) is not deny_first_probe
    assert probes == (1 if deny_first_probe else 2)
    assert state["cleanup_pass"] is False
    assert state["group_exited"] is False
    assert "PermissionError" in state["group_probe_error"]


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
