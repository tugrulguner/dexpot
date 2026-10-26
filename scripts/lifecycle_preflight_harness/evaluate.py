"""Fail-closed validation and paired screening for bounded benchmark records."""

from __future__ import annotations

import math
from typing import Any


def _number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (not positive or value > 0)
        and (not nonnegative or value >= 0)
    )


def _validate(
    plan: dict[str, Any], trials: list[dict[str, Any]]
) -> tuple[list[str], int, int, int]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan must be an object"], 0, len(trials) if isinstance(trials, list) else 0, 0
    matrix = plan.get("matrix") if isinstance(plan, dict) else None
    expected = len(matrix) if isinstance(matrix, list) else 0
    completed = len(trials) if isinstance(trials, list) else 0
    valid = 0
    if plan.get("schema") != 1 or not isinstance(matrix, list) or not matrix:
        errors.append("plan requires schema 1 and a nonempty matrix")
        return errors, expected, completed, valid
    ids = [c.get("id") for c in matrix if isinstance(c, dict)]
    if (
        len(ids) != len(matrix)
        or not all(isinstance(i, str) and i for i in ids)
        or len(set(ids)) != len(ids)
    ):
        errors.append("matrix has invalid or duplicate ids")
        return errors, expected, completed, valid
    if any(
        c.get("runtime") not in ("gil", "ft") or c.get("profile") not in ("flat", "nested", "mixed")
        for c in matrix
    ):
        return ["unsupported runtime or workload"], expected, completed, valid
    if not isinstance(trials, list):
        return [*errors, "trials must be a list"], expected, 0, valid
    seen: set[str] = set()
    budgets = plan.get("budgets", {})
    if not isinstance(budgets, dict):
        return ["budgets must be an object"], expected, completed, valid
    for key in ("rss_bytes", "threads", "fds", "cpu_cores"):
        if not _number(budgets.get(key), positive=True):
            errors.append(f"invalid budget: {key}")
    for trial in trials:
        if not isinstance(trial, dict):
            errors.append("trial must be an object")
            continue
        cell = trial.get("cell")
        ident = cell.get("id") if isinstance(cell, dict) else None
        match = next((c for c in matrix if isinstance(c, dict) and c.get("id") == ident), None)
        if (
            not isinstance(cell, dict)
            or not isinstance(ident, str)
            or match is None
            or cell != match
            or ident in seen
        ):
            errors.append(f"unexpected, mismatched, or duplicate cell: {ident}")
            continue
        seen.add(ident)
        okay = True
        m, r, res = trial.get("metrics"), trial.get("runtime"), trial.get("resources")
        if not isinstance(m, dict) or not isinstance(r, dict) or not isinstance(res, dict):
            errors.append(f"missing trial objects: {ident}")
            continue
        for k in (
            "requests",
            "good",
            "bad",
            "connect_errors",
            "read_errors",
            "write_errors",
            "timeout_errors",
            "duration_us",
            "p50_us",
            "p95_us",
            "p99_us",
        ):
            if not _number(
                m.get(k),
                positive=k in ("requests", "good", "duration_us", "p50_us", "p95_us", "p99_us"),
                nonnegative=k
                not in ("requests", "good", "duration_us", "p50_us", "p95_us", "p99_us"),
            ):
                okay = False
        if m.get("good") != m.get("requests") or any(
            m.get(k) != 0
            for k in ("bad", "connect_errors", "read_errors", "write_errors", "timeout_errors")
        ):
            okay = False
        for key in (
            "requests",
            "good",
            "bad",
            "connect_errors",
            "read_errors",
            "write_errors",
            "timeout_errors",
        ):
            if type(m.get(key)) is not int:
                okay = False
        runtime = cell.get("runtime")
        if (
            r.get("gil_enabled") is not (runtime == "gil")
            or r.get("ft_build") is not (runtime == "ft")
            or not isinstance(r.get("version"), str)
            or not r.get("version")
            or "/site-packages/dexpot/" not in r.get("module", "")
        ):
            okay = False
        for k in ("rss_bytes", "threads", "fds"):
            if (
                not _number(res.get(k), positive=True)
                or not _number(budgets.get(k), positive=True)
                or res.get(k, math.inf) > budgets.get(k, 0)
            ):
                okay = False
        if (
            res.get("complete") is not True
            or not _number(res.get("cpu_cores"), nonnegative=True)
            or not _number(budgets.get("cpu_cores"), positive=True)
            or res.get("cpu_cores", math.inf) > budgets.get("cpu_cores", 0)
        ):
            okay = False
        if (
            trial.get("client_returncode") != 0
            or trial.get("cleanup_pass") is not True
            or trial.get("error") is not None
        ):
            okay = False
        if okay:
            valid += 1
        else:
            errors.append(f"invalid trial: {ident}")
    if seen != set(ids):
        errors.append("missing matrix cells")
    return errors, expected, completed, valid


def evaluate(
    plan: dict[str, Any], trials: list[dict[str, Any]], preflights: dict[str, Any]
) -> dict[str, Any]:
    errors, expected, completed, valid = _validate(plan, trials)
    runtimes = (
        {
            c["runtime"]
            for c in plan.get("matrix", [])
            if isinstance(c, dict) and c.get("runtime") in ("gil", "ft")
        }
        if isinstance(plan, dict) and isinstance(plan.get("matrix"), list)
        else set()
    )
    for runtime in runtimes:
        pf = preflights.get(runtime, {}) if isinstance(preflights, dict) else {}
        if not isinstance(pf, dict) or any(
            pf.get(k) is not True for k in ("churn_pass", "overload_pass", "cleanup_pass")
        ):
            errors.append(f"missing or failed {runtime} preflight")
    return {
        "status": "baseline-recorded" if not errors and valid == expected else "invalid",
        "errors": errors,
        "expected": expected,
        "completed": completed,
        "valid": valid,
    }


def compare(
    plan: dict[str, Any],
    baseline_trials: list[dict[str, Any]],
    candidate_trials: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = []
    b_errors, expected, _, b_valid = _validate(plan, baseline_trials)
    c_errors, c_expected, _, c_valid = _validate(plan, candidate_trials)
    errors.extend(f"baseline: {e}" for e in b_errors)
    errors.extend(f"candidate: {e}" for e in c_errors)
    limits = plan.get("comparison", {}) if isinstance(plan, dict) else {}
    minimum: Any = limits.get("min_goodput_ratio")
    maximum: Any = limits.get("max_adjusted_p99_ratio")
    if (
        not _number(minimum, positive=True)
        or minimum > 1
        or not _number(maximum, positive=True)
        or maximum < 1
    ):
        errors.append("invalid comparison limits")
    pairs = []
    if not errors and expected == c_expected and b_valid == expected and c_valid == expected:
        base = {t["cell"]["id"]: t for t in baseline_trials}
        cand = {t["cell"]["id"]: t for t in candidate_trials}
        for cell in plan["matrix"]:
            ident = cell["id"]
            bt, ct = base[ident], cand[ident]
            bg = bt["metrics"]["good"] / (bt["metrics"]["duration_us"] / 1_000_000)
            cg = ct["metrics"]["good"] / (ct["metrics"]["duration_us"] / 1_000_000)
            gr = cg / bg
            pr = ct["metrics"]["p99_us"] / bt["metrics"]["p99_us"]
            pairs.append(
                {
                    "id": ident,
                    "goodput_ratio": gr,
                    "p99_ratio": pr,
                    "passed": gr >= minimum and pr <= maximum,
                }
            )
    passed = bool(pairs) and all(p["passed"] for p in pairs)
    return {
        "status": "invalid" if errors else "screen-passed" if passed else "regression",
        "errors": errors,
        "pairs": pairs,
    }
