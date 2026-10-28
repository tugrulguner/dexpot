"""Synthetic orchestration tests; never runtime or performance evidence."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "socket_owner_diagnostic", ROOT / "scripts/socket_owner_diagnostic.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_window_order_is_balanced_and_keeps_original_matrix():
    assert [role for _, role in MODULE.order(0)] == ["main", "pr", "pr", "main"]
    assert [role for _, role in MODULE.order(1)] == ["pr", "main", "main", "pr"]
    for index in range(12):
        assert len({side for side, _ in MODULE.order(index)}) == 4
        assert sorted(role for _, role in MODULE.order(index)) == ["main", "main", "pr", "pr"]


def run_synthetic(tmp_path, monkeypatch, product_status):
    cells = json.loads((ROOT / "scripts/lifecycle_preflight_harness/plan.json").read_text())[
        "matrix"
    ]
    calls = []

    def record(cell, cohort, side, artifact, harness):
        calls.append((cell["id"], side, artifact))
        return tmp_path / side

    def calibrate(left, right, cell):
        return {
            "status": "regression",
            "errors": [],
            "pairs": [{"id": cell["id"], "passed": False}],
        }

    def product(*args):
        return {"returncode": 1, "comparison": {"status": product_status, "errors": []}}

    monkeypatch.setattr(MODULE, "product", product)
    result = MODULE.diagnostic(
        cells, record, calibrate, ROOT / "scripts/lifecycle_preflight_harness", tmp_path, tmp_path
    )
    for index, cell in enumerate(cells):
        assert calls[index * 4 : index * 4 + 4] == [
            (cell["id"], side, artifact) for side, artifact in MODULE.order(index)
        ]
    assert len(calls) == 48
    assert len(result["aa"]) == len(result["ab"]) == 24
    assert not result["qualified"]
    summary = json.loads((tmp_path / "diagnostic-summary.json").read_text())
    assert (
        not summary["qualified"]
        and summary["original_gate"] == "blocked-by-retained-stock-controls"
    )
    assert all(row["comparison"]["status"] == "regression" for row in result["aa"])
    return result


def test_numeric_losses_retained_without_suppressing_candidate_observation(tmp_path, monkeypatch):
    result = run_synthetic(tmp_path, monkeypatch, "regression")
    assert result["status"] == "diagnostic-complete" and not result["qualified"]


def test_invalid_trials_retained_without_false_success(tmp_path, monkeypatch):
    result = run_synthetic(tmp_path, monkeypatch, "invalid")
    assert result["status"] == "diagnostic-invalid" and not result["qualified"]


def test_cli_prepare_entrypoint_cannot_qualify(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    request.write_text(json.dumps(MODULE.request_spec()))
    calls = []
    monkeypatch.setattr(
        MODULE.sys, "argv", ["diagnostic", "--run-request", str(request), "--prepare-only"]
    )
    monkeypatch.setattr(
        MODULE.DRIVER, "execute_qualification", lambda diagnostic: calls.append(diagnostic) or 0
    )
    assert MODULE.main() == 0
    assert calls == [MODULE.diagnostic] and MODULE.DRIVER.PREPARE_ONLY
    assert MODULE.DRIVER.RUN_REQUEST["qualified"] is False
    assert MODULE.DRIVER.HEAD == MODULE.CANDIDATE
