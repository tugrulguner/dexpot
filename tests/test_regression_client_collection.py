"""Unit fixtures test output retention; these are not benchmark measurements."""

import contextlib
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("already_exited", [True, False])
def test_trial_collects_client_output_when_sampling_raises(monkeypatch, tmp_path, already_exited):
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/run.py"))
    trial = api["trial"]
    scope = trial.__globals__
    runtime = {
        "module": "/fixture/site-packages/dexpot/__init__.py",
        "version": "fixture",
        "gil_enabled": True,
        "ft_build": False,
        "selected_ft": False,
        "parser": "python",
    }
    metrics = {
        "requests": 10,
        "good": 10,
        "bad": 0,
        "duration_us": 1000000,
        "p50_us": 1,
        "p95_us": 2,
        "p99_us": 3,
        "connect_errors": 0,
        "read_errors": 0,
        "write_errors": 0,
        "timeout_errors": 0,
        "flat_good": 10,
        "nested_good": 0,
        "cpu_good": 0,
        "io_good": 0,
    }
    output = "METRICS " + json.dumps(metrics) + "\n"
    state = {"runtime": runtime, "cleanup_pass": True}

    @contextlib.contextmanager
    def server(*args):
        yield SimpleNamespace(pid=100), 12345, state

    class Client:
        pid = 200
        returncode = None

        def __init__(self):
            self.polls = 0
            self.collected = False
            self.killed = False

        def poll(self):
            self.polls += 1
            if self.polls > 1 and already_exited and not self.killed:
                self.returncode = 0
            return self.returncode

        def communicate(self, timeout):
            self.collected = True
            self.returncode = -9 if self.killed else 0
            return output, ""

        def kill(self):
            assert not already_exited, "already finished fixture client must not be killed"
            self.killed = True
            self.returncode = -9

    client = Client()
    stamp = 0

    def snapshot(process):
        nonlocal stamp
        if process.pid == client.pid:
            raise psutil.AccessDenied(client.pid)
        stamp += 1
        return {"t": stamp, "cpu": stamp / 10, "rss": 1000, "threads": 1, "fds": 3, "children": 0}

    def request(port, path):
        return (200, json.dumps(runtime).encode()) if path == "/runtime" else (200, scope["FLAT"])

    monkeypatch.setitem(scope, "server", server)
    monkeypatch.setitem(scope, "verify_runtime", lambda *args: None)
    monkeypatch.setitem(scope, "fingerprints", lambda args: {})
    monkeypatch.setitem(scope, "snapshot", snapshot)
    monkeypatch.setitem(scope, "request", request)
    monkeypatch.setattr(scope["subprocess"], "Popen", lambda *args, **kwargs: client)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(pid=pid))
    args = SimpleNamespace(wrk=Path("/fixture/wrk"), identities={"gil": runtime})
    cell = {"id": "gil-flat-0", "runtime": "gil", "profile": "flat", "repeat": 0}
    plan = {"duration_s": 1, "connections": 16, "client_threads": 4}
    row = trial(cell, plan, "python", {}, tmp_path, args, {})
    assert client.collected, "sampling failure must not discard the owned client's pipes"
    assert row["stdout"] == output
    assert row["metrics"] == metrics
    if already_exited:
        assert row["client_returncode"] == 0
        assert row["error"] is None, "confirmed exit race must be distinguished from live denial"
        assert row["client_exit_sample_errors"]
    else:
        assert row["client_returncode"] == -9
        assert "AccessDenied" in row["error"]
        assert "client_exit_sample_errors" not in row
