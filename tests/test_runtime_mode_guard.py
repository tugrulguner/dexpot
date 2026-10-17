"""Contract tests for the real-server runtime mode guard."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_runtime_mode.py"


@pytest.mark.parametrize("misdirected", [False, True])
def test_guard_anchors_identity_to_server_not_windows_venv_redirector(
    monkeypatch, tmp_path, misdirected
):
    spec = importlib.util.spec_from_file_location("runtime_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    info = {
        "pid": 4002,
        "free_threaded_build": False,
        "gil_enabled": True,
        "selected_gil_enabled": True,
        "execution_mode": "pooled-gil",
        "launch_overrides": {"PYTHON_GIL": None, "gil": None},
    }

    class Redirector:
        pid = 4001
        returncode = 0

        def __init__(self, command, **kwargs):
            record = Path(command[command.index("--import-record") + 1])
            record.write_text(
                json.dumps({**info, "selected_gil_enabled": None, "execution_mode": "unbound"})
            )

        def poll(self):
            return None

        def terminate(self):
            pass

        def communicate(self, **kwargs):
            return "", ""

    def http(base, path, data=None):
        if path == "/runtime":
            return 200, json.dumps({**info, "pid": 4003 if misdirected else 4002}).encode()
        if path == "/typed":
            return (422, b"") if data == b'{"value":"bad"}' else (200, b'{"value":8}')
        return {"/invalid": (500, b""), "/raw": (200, b"ready"), "/lazy": (200, b'{"lazy":true}')}[
            path
        ]

    monkeypatch.setattr(guard.subprocess, "Popen", Redirector)
    monkeypatch.setattr(guard, "http", http)
    result = guard.run_case("gil", tmp_path)
    assert result["valid"] is (not misdirected), result


def test_guard_requires_explicit_expected_mode() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "--expect" in result.stderr


def test_guard_rejects_unknown_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--expect", "surprise"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_guard_observes_real_server_lifecycle_without_forcing_gil():
    build = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    mode = (
        "ft"
        if build and not getattr(sys, "_is_gil_enabled", lambda: True)()
        else ("ft-gil" if build else "gil")
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHON_GIL"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--expect", mode],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["positive"]["valid"] is True
    snapshots = report["positive"]["snapshots"]
    assert [row["phase"] for row in snapshots] == [
        "after_application_import",
        "after_startup",
        "after_routes",
        "after_lazy_import",
    ]
    assert len({row["pid"] for row in snapshots}) == 1
    assert all(row["launch_overrides"] == {"PYTHON_GIL": None, "gil": None} for row in snapshots)
    assert all("msgspec" in row["dependencies"] for row in snapshots)


@pytest.mark.parametrize("override", ["1", "0"])
def test_ft_guard_rejects_a_forcing_override(override):
    if override == "0" and not sysconfig.get_config_var("Py_GIL_DISABLED"):
        pytest.skip("standard CPython rejects disabling the GIL before the guard runs")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--expect", "ft"],
        env={**os.environ, "PYTHON_GIL": override},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "override" in result.stderr


@pytest.mark.skipif(
    os.name != "posix"
    or not sysconfig.get_config_var("Py_GIL_DISABLED")
    or getattr(sys, "_is_gil_enabled", lambda: True)(),
    reason="automatic native fallback needs an unforced POSIX FT interpreter",
)
def test_real_unsupported_extension_is_detected_at_startup_and_lazy_import():
    env = {key: value for key, value in os.environ.items() if key != "PYTHON_GIL"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--expect", "ft", "--negative-extension"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["automatic_fallback_detected"] == ["startup", "lazy"]
    assert all(
        not row["valid"] and row["failure_kind"] == "runtime_mode" for row in report["negative"]
    )
    assert report["ft_gil_enabled"]["valid"] is True
