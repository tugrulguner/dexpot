import importlib.util
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).parents[1] / "benchmarks/regression/evaluate.py"
_SPEC = importlib.util.spec_from_file_location("regression_evaluate", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def records() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    cells = [
        {"id": "gil-flat-0", "runtime": "gil", "profile": "flat", "repeat": 0},
        {"id": "ft-flat-0", "runtime": "ft", "profile": "flat", "repeat": 0},
    ]
    trials = []
    for cell in cells:
        trials.append(
            {
                "cell": cell,
                "metrics": {
                    "requests": 10,
                    "good": 10,
                    "bad": 0,
                    "connect_errors": 0,
                    "read_errors": 0,
                    "write_errors": 0,
                    "timeout_errors": 0,
                    "duration_us": 1_000_000,
                    "p50_us": 10,
                    "p95_us": 20,
                    "p99_us": 30,
                },
                "runtime": {
                    "gil_enabled": cell["runtime"] == "gil",
                    "ft_build": cell["runtime"] == "ft",
                    "module": "/site-packages/dexpot/__init__.py",
                    "version": "0.7.1",
                },
                "resources": {
                    "complete": True,
                    "rss_bytes": 100,
                    "threads": 2,
                    "fds": 3,
                    "cpu_cores": 1.0,
                },
                "client_returncode": 0,
                "cleanup_pass": True,
                "error": None,
            }
        )
    plan = {
        "schema": 1,
        "matrix": cells,
        "budgets": {"rss_bytes": 536870912, "threads": 128, "fds": 256, "cpu_cores": 12},
        "comparison": {"min_goodput_ratio": 0.90, "max_adjusted_p99_ratio": 1.25},
    }
    preflights = {
        r: {"churn_pass": True, "overload_pass": True, "cleanup_pass": True} for r in ("gil", "ft")
    }
    return plan, trials, preflights


def test_evaluate_records_complete_qualified_baseline():
    plan, trials, preflights = records()
    result = _MODULE.evaluate(plan, trials, preflights)
    assert result["status"] == "baseline-recorded"
    assert (result["expected"], result["completed"], result["valid"]) == (2, 2, 2)
    assert result["errors"] == []


def test_evaluate_rejects_duplicate_cells():
    plan, trials, preflights = records()
    result = _MODULE.evaluate(plan, [*trials, trials[0]], preflights)
    assert result["status"] == "invalid"
    assert result["valid"] == 2
    assert result["errors"]


def test_compare_fails_candidate_regression_without_dropping_pair():
    plan, baseline, _ = records()
    _, candidate, _ = records()
    candidate[1]["metrics"]["duration_us"] = 2_000_000
    result = _MODULE.compare(plan, baseline, candidate)
    assert result["status"] == "regression"
    assert len(result["pairs"]) == 2
    assert not result["pairs"][1]["passed"]


@pytest.mark.parametrize("field", ["metrics", "runtime", "resources"])
def test_missing_trial_objects_fail_closed(field):
    plan, trials, preflights = records()
    trials[0][field] = None
    assert _MODULE.evaluate(plan, trials, preflights)["status"] == "invalid"


@pytest.mark.parametrize(
    "key,value",
    [
        ("bad", 1),
        ("read_errors", 1),
        ("good", float("nan")),
        ("requests", 10.5),
        ("duration_us", 0),
        ("p99_us", float("inf")),
    ],
)
def test_invalid_native_counters_never_qualify(key, value):
    plan, trials, preflights = records()
    trials[0]["metrics"][key] = value
    if key == "requests":
        trials[0]["metrics"]["good"] = value
    assert _MODULE.evaluate(plan, trials, preflights)["status"] == "invalid"


@pytest.mark.parametrize(
    "key,value", [("cpu_cores", 0), ("cpu_cores", None), ("threads", None), ("fds", True)]
)
def test_invalid_budgets_fail_closed(key, value):
    plan, trials, preflights = records()
    plan["budgets"][key] = value
    assert _MODULE.evaluate(plan, trials, preflights)["status"] == "invalid"


def test_missing_cells_preflights_and_failed_cleanup_never_qualify():
    plan, trials, preflights = records()
    assert _MODULE.evaluate(plan, trials[:1], preflights)["status"] == "invalid"
    assert _MODULE.evaluate(plan, trials, {})["status"] == "invalid"
    trials[0]["cleanup_pass"] = False
    assert _MODULE.evaluate(plan, trials, preflights)["status"] == "invalid"


def test_new_candidate_version_is_not_rejected_by_hardcoded_baseline_version():
    plan, baseline, _ = records()
    _, candidate, _ = records()
    for trial in candidate:
        trial["runtime"]["version"] = "0.8.0"
    assert _MODULE.compare(plan, baseline, candidate)["status"] == "screen-passed"


@pytest.mark.parametrize("change", ["budgets", "id", "runtime", "preflight"])
def test_malformed_plan_and_control_objects_return_invalid(change):
    plan, trials, preflights = records()
    if change == "budgets":
        plan["budgets"] = None
    elif change == "id":
        plan["matrix"][0]["id"] = []
    elif change == "runtime":
        plan["matrix"][0]["runtime"] = "unknown"
    else:
        preflights["gil"] = None
    assert _MODULE.evaluate(plan, trials, preflights)["status"] == "invalid"
