"""Result parsing must fail closed before native timed traffic is used."""

import builtins
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "benchmarks/regression/run.py"


def test_benchmark_sources_participate_in_canonical_quality_gates():
    makefile = (RUNNER.parents[2] / "Makefile").read_text()
    commands = [
        line
        for line in makefile.splitlines()
        if line.startswith("\tuv run ruff") or line.startswith("\tuv run pyright")
    ]
    assert len(commands) == 5
    assert all("benchmarks/regression/" in command for command in commands)


def test_parser_import_does_not_require_optional_benchmark_dependencies(monkeypatch):
    original = builtins.__import__

    def without_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ModuleNotFoundError("optional benchmark dependency deliberately unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_psutil)
    assert callable(runpy.run_path(str(RUNNER))["parse_metrics"])


def test_worker_identity_must_match_the_verified_installation():
    namespace = runpy.run_path(str(RUNNER))
    assert "verify_runtime" in namespace
    verify = namespace["verify_runtime"]
    expected = {
        "module": "/venv/site-packages/dexpot/__init__.py",
        "version": "0.7.1",
        "gil_enabled": True,
        "ft_build": False,
    }
    observed = dict(expected, parser="python", selected_ft=False)
    verify(observed, expected, "gil")
    for key, value in (
        ("module", "/source/dexpot.py"),
        ("version", "wrong"),
        ("parser", "native"),
        ("selected_ft", True),
        ("gil_enabled", False),
        ("ft_build", True),
    ):
        with pytest.raises(ValueError):
            verify(dict(observed, **{key: value}), expected, "gil")


def test_plan_admits_every_persistent_connection_before_timing():
    namespace = runpy.run_path(str(RUNNER))
    assert "validate_plan" in namespace
    validate = namespace["validate_plan"]
    plan = json.loads(RUNNER.with_name("plan.json").read_text())
    validate(dict(plan, pool=16))
    with pytest.raises(ValueError, match="persistent"):
        validate(dict(plan, pool=8))


def test_native_metrics_parser_requires_one_complete_finite_record():
    assert RUNNER.exists(), "the regression screen needs a checked native-result parser"
    parse = runpy.run_path(str(RUNNER))["parse_metrics"]
    metrics = dict(
        requests=10,
        good=10,
        bad=0,
        duration_us=1_000_000,
        p50_us=1,
        p95_us=2,
        p99_us=3,
        connect_errors=0,
        read_errors=0,
        write_errors=0,
        timeout_errors=0,
        flat_good=10,
        nested_good=0,
        cpu_good=0,
        io_good=0,
    )
    line = "METRICS " + json.dumps(metrics)
    assert parse(line, "flat") == metrics
    for output in ("", line + "\n" + line, line.replace('"good": 10', '"good": NaN')):
        with pytest.raises(ValueError):
            parse(output, "flat")
    with pytest.raises(ValueError):
        parse(line, "mixed")


@pytest.mark.skipif(
    not os.environ.get("DEXPOT_SCREEN_TEST_PYTHON"),
    reason="opt-in installed-wheel/native-wrk smoke; not a noisy CI performance gate",
)
def test_record_cli_executes_native_trial_and_refuses_overwriting_evidence(tmp_path):
    plan = json.loads(RUNNER.with_name("plan.json").read_text())
    plan["matrix"] = [plan["matrix"][0]]
    plan["duration_s"] = 1
    config = tmp_path / "smoke-plan.json"
    config.write_text(json.dumps(plan))
    output = tmp_path / "observations"
    command = [
        sys.executable,
        str(RUNNER),
        "record",
        "--plan",
        str(config),
        "--python-gil",
        os.environ["DEXPOT_SCREEN_TEST_PYTHON"],
        "--wheel",
        os.environ["DEXPOT_SCREEN_TEST_WHEEL"],
        "--wrk",
        os.environ["DEXPOT_SCREEN_TEST_WRK"],
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "baseline-recorded" and report["completed"] == 1
    row = json.loads((output / "gil-flat-0.json").read_text())
    assert row["metrics"]["requests"] == row["metrics"]["good"] > 0
    assert row["cleanup_pass"] is True
    frozen = (output / "gil-flat-0.json").read_bytes()
    again = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert again.returncode != 0
    assert frozen == (output / "gil-flat-0.json").read_bytes()
    comparison = tmp_path / "comparison.json"
    rejected = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "compare",
            "--baseline",
            str(output),
            "--candidate",
            str(output),
            "--output",
            str(comparison),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rejected.returncode == 1
    assert json.loads(comparison.read_text())["status"] == "invalid"
    row["runtime"]["version"] = "detached-observation"
    (output / "gil-flat-0.json").write_text(json.dumps(row))
    resumed = subprocess.run([*command, "--resume"], capture_output=True, text=True, timeout=10)
    assert resumed.returncode != 0, "resume accepted a trial from a different serving identity"
