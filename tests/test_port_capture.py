"""Capture lifecycle tests use an owned synthetic subprocess, never privileged capture."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "port_capture", Path(__file__).parents[1] / "scripts/port_capture.py"
)
assert SPEC is not None and SPEC.loader is not None
CAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAP)


def test_capture_scoped_readiness_stop_and_footer(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def fake_popen(command, **kwargs):
        assert command[-1] == "tcp port 43210 and host 127.0.0.1"
        assert command[command.index("-i") + 1] == "lo0"
        Path(command[command.index("-w") + 1]).write_bytes(b"synthetic-unit-only")
        program = "import signal,sys,time; signal.signal(signal.SIGINT,lambda *a:(sys.stderr.write('1 packets captured\\n1 packets received by filter\\n0 packets dropped by kernel\\n'),sys.stderr.flush(),sys.exit(0))); sys.stderr.write('data link type NULL\\nlistening on lo0\\n'); sys.stderr.flush(); time.sleep(30)"
        return real_popen([sys.executable, "-c", program], **kwargs)

    def fake_run(command, **kwargs):
        assert command[:2] == ["sudo", "-n"]
        if "/bin/kill" in command:
            os.killpg(int(command[-1].lstrip("-")), signal.SIGINT)
        else:
            assert command[2] == "chown"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(CAP.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(CAP.subprocess, "run", fake_run)
    root = tmp_path / "capture"
    with CAP.capture_port(43210, root) as state:
        assert state["ready"]
    actual = json.loads((root / "capture.json").read_text())
    assert actual["kernel_dropped"] == 0 and actual["stop_returncode"] == 0


def test_personal_host_capture_rejected(tmp_path, monkeypatch):
    import pytest

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with (
        pytest.raises(RuntimeError, match="disposable GitHub CI"),
        CAP.capture_port(43210, tmp_path / "never"),
    ):
        raise AssertionError("must not start")
