import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "socket_runtime_qualification",
    Path(__file__).parents[1] / "scripts/socket_runtime_qualification.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def cells():
    return [{"id": f"cell-{index}"} for index in range(12)]


def row(cell, cohort, status="screen-passed", rc=0):
    return {
        "id": cell["id"],
        "cohort": cohort,
        "returncode": rc,
        "comparison": {"status": status},
    }


def test_exactly_aa_then_ab_order_and_both_direction_schedule():
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append((cell["id"], cohort, sides, reverse))
        return row(cell, cohort)

    verdict = MODULE.run_stages(cells(), pair)
    assert verdict["qualified"]
    assert [item[1] for item in calls] == ["aa"] * 12 + ["ab"] * 12
    assert [item[3] for item in calls[:12]] == [bool(i % 2) for i in range(12)]
    assert [item[3] for item in calls[12:]] == [bool(i % 2) for i in range(12)]
    assert all(c[2] == [("left", "base"), ("right", "base")] for c in calls[:12])
    assert all(c[2] == [("base", "base"), ("candidate", "candidate")] for c in calls[12:])


def test_any_aa_failure_skips_every_ab_pair():
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append(cohort)
        return row(
            cell,
            cohort,
            "regression" if cohort == "aa" and cell["id"] == "cell-5" else "screen-passed",
        )

    verdict = MODULE.run_stages(cells(), pair)
    assert not verdict["qualified"]
    assert verdict["completed_aa"] == 12 and verdict["completed_ab"] == 0
    assert calls == ["aa"] * 12
    assert verdict["aa"][5]["comparison"]["status"] == "regression"


def test_ab_failure_preserved_and_fails_closed():
    def pair(cell, cohort, sides, reverse):
        return row(cell, cohort, rc=1 if cohort == "ab" and cell["id"] == "cell-2" else 0)

    verdict = MODULE.run_stages(cells(), pair)
    assert not verdict["qualified"] and verdict["completed_ab"] == 12
    assert verdict["ab"][2]["returncode"] == 1


def test_missing_duplicate_and_control_only_never_qualify():
    expected = [c["id"] for c in cells()]
    valid = [row(c, "aa") for c in cells()]
    assert not MODULE.cohort_passes(valid[:-1], expected)
    assert not MODULE.cohort_passes([*valid[:-1], valid[0]], expected)
    assert not MODULE.cohort_passes(
        [row(c, "aa", "regression") if c["id"] == "cell-0" else row(c, "aa") for c in cells()],
        expected,
    )
    control = MODULE.result(valid, [row(c, "ab") for c in cells()], expected, controls=True)
    assert control["status"] == "screen-failed" and not control["qualified"]


def test_duplicate_matrix_rejected_before_any_pair():
    duplicate = cells()
    duplicate[-1] = {"id": duplicate[0]["id"]}
    invoked = []
    try:
        MODULE.run_stages(duplicate, lambda *args: invoked.append(args))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate matrix must reject")
    assert not invoked


def test_controls_only_never_runs_candidate_pairs():
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append(cohort)
        return row(cell, cohort)

    verdict = MODULE.run_stages(cells(), pair, controls=True)
    assert calls == ["aa"] * 12
    assert not verdict["qualified"] and verdict["completed_ab"] == 0


def test_cli_run_request_reaches_real_runner(monkeypatch):
    request = Path(__file__).parents[1] / "benchmarks/socket-runtime-run-request.json"
    reached = []
    monkeypatch.setattr(MODULE, "PREPARE_ONLY", False)
    monkeypatch.setattr(
        MODULE, "execute_qualification", lambda: reached.append(MODULE.RUN_REQUEST) or 0
    )
    monkeypatch.setattr(
        MODULE.sys, "argv", ["qualification", "--run-request", str(request), "--prepare-only"]
    )
    assert MODULE.main() == 0
    assert reached[0]["candidate_sha"] == MODULE.HEAD and MODULE.PREPARE_ONLY


def test_request_rejects_relaxed_budgets(tmp_path, monkeypatch):
    import json

    import pytest

    original = Path(__file__).parents[1] / "benchmarks/socket-runtime-run-request.json"
    request = json.loads(original.read_text())
    request["comparison"]["min_goodput_ratio"] = 0.5
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(request))
    monkeypatch.setattr(MODULE, "PREPARE_ONLY", True)
    with pytest.raises(ValueError, match="original budgets"):
        MODULE.validate_request(changed)


def test_aa_numerical_calibration_is_exact_reused_function():
    import ast

    root = Path(__file__).parents[1]

    def calibration(path):
        tree = ast.parse(path.read_text())
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "calibrate"
        )

    original = calibration(root / "scripts/controlled_lifecycle_qualification.py")
    current = calibration(root / "scripts/socket_runtime_qualification.py")
    assert ast.dump(original) == ast.dump(current)
