"""Strict lifecycle validation for benchmark evidence, not synthetic measurements."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "benchmarks/checked_execution/runtime_identity.py"


def helper():
    spec = importlib.util.spec_from_file_location("benchmark_identity", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(pid, phase):
    return {
        "phase": phase,
        "pid": pid,
        "python": "test-interpreter",
        "free_threaded_build": True,
        "gil_enabled": False,
        "selected_gil_enabled": False,
        "execution_mode": "bounded-ft",
        "launch_overrides": {"PYTHON_GIL": None, "gil": None},
        "dependencies": {"dexpot": "test-version", "msgspec": "test-version"},
        "active_connections": 0,
    }


def log(events):
    return "unrelated startup log\n" + "\n".join(
        "RUNTIME_IDENTITY " + json.dumps(row) for row in events
    )


def test_accepts_complete_matching_worker_lifecycles():
    events = [event(pid, phase) for pid in [1001, 1002] for phase in ["startup", "after_workload"]]
    result = helper().validate_runtime_events(
        log(events), expected_runtime="ft", expected_processes=2
    )
    assert result["valid"] is True
    assert result["pids"] == [1001, 1002]


@pytest.mark.parametrize(
    "field,value",
    [
        ("gil_enabled", True),
        ("free_threaded_build", False),
        ("selected_gil_enabled", True),
        ("execution_mode", "pooled-gil"),
        ("launch_overrides", {"PYTHON_GIL": "0", "gil": None}),
        ("launch_overrides", {"PYTHON_GIL": None, "gil": "0"}),
        ("dependencies", {}),
        ("active_connections", 1),
    ],
)
def test_invalidates_mislabeled_or_incomplete_post_workload_evidence(field, value):
    startup, final = event(1001, "startup"), event(1001, "after_workload")
    final[field] = value
    result = helper().validate_runtime_events(
        log([startup, final]), expected_runtime="ft", expected_processes=1
    )
    assert result["valid"] is False
    assert result["errors"]


@pytest.mark.parametrize(
    "events,processes",
    [
        ([event(1001, "startup")], 1),
        ([event(1001, "startup"), event(1002, "after_workload")], 1),
        ([event(1001, "startup"), event(1001, "after_workload")], 2),
        ([event(1001, "startup"), event(1001, "startup"), event(1001, "after_workload")], 1),
    ],
)
def test_rejects_missing_duplicate_or_wrong_process_records(events, processes):
    assert (
        helper().validate_runtime_events(
            log(events), expected_runtime="ft", expected_processes=processes
        )["valid"]
        is False
    )


def test_rejects_malformed_identity_record_without_hiding_it():
    result = helper().validate_runtime_events(
        "RUNTIME_IDENTITY not-json", expected_runtime="ft", expected_processes=1
    )
    assert result["valid"] is False
    assert any("malformed" in reason for reason in result["errors"])


@pytest.mark.parametrize("workers", [1, 2])
def test_actual_benchmark_workers_report_startup_and_after_workload(workers):
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    if not gil and workers > 1:
        pytest.skip("FT serves in one process")
    if os.name != "posix" and workers > 1:
        pytest.skip("multiprocess serving requires POSIX")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    root = PATH.parent
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DEXPOT_", "COMPARE_"))
    }
    env.update(
        COMPARE_FRAMEWORK="dexpot",
        COMPARE_CONTRACT="native",
        COMPARE_WORKERS=str(workers),
        COMPARE_SYNC_THREADS="2",
        COMPARE_PORT=str(port),
        DEXPOT_HTTP_PARSER="python",
    )
    process = subprocess.Popen(
        [sys.executable, str(root / "app.py")],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            assert process.poll() is None, "benchmark server exited during startup"
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/items/7", timeout=2
                ) as response:
                    assert response.read() == b'{"id":7,"name":"item-7","price":9.99}'
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("benchmark server startup timed out")
                time.sleep(0.025)
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail("benchmark server did not drain")
    result = helper().validate_runtime_events(
        stdout, expected_runtime="gil" if gil else "ft", expected_processes=workers
    )
    assert result["valid"] is True, str(result) + stderr
