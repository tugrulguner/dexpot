"""One balanced stock/repair diagnostic; cannot clear failed qualification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = "9b40acd985fbf3844430b789524a6ca1aff06ab3"
HELPER = REPO / "scripts/socket_runtime_qualification.py"
SPEC = importlib.util.spec_from_file_location("socket_qualification", HELPER)
assert SPEC and SPEC.loader
DRIVER: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


def order(index):
    stock = [("base-a", "main"), ("base-b", "main")]
    repair = [("repair-a", "pr"), ("repair-b", "pr")]
    return (
        [stock[0], repair[0], repair[1], stock[1]]
        if index % 2 == 0
        else [repair[0], stock[0], stock[1], repair[1]]
    )


def request_spec():
    plan = json.loads((REPO / "scripts/lifecycle_preflight_harness/plan.json").read_text())
    return {
        "schema": 1,
        "kind": "balanced-socket-owner-diagnostic-not-qualification",
        "base_sha": DRIVER.BASE,
        "candidate_sha": CANDIDATE,
        "failed_qualification_retained": "40607601578",
        "failed_candidate_retained": "40609444989",
        "duration_s": 15,
        "client_threads": plan["client_threads"],
        "connections": plan["connections"],
        "pool": plan["pool"],
        "budgets": plan["budgets"],
        "comparison": plan["comparison"],
        "sequence": "all 12 original cells once; ABBA on even indices, BAAB on odd; A=stock, B=repair",
        "question": "Measure stock and repair repeatability plus directional differences without requiring unstable stock controls to pass; diagnostics cannot clear the original failed promotion gate.",
        "no_retries": True,
        "qualified": False,
        "helper_sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
        "diagnostic_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "plan_sha256": hashlib.sha256(
            (REPO / "scripts/lifecycle_preflight_harness/plan.json").read_bytes()
        ).hexdigest(),
    }


def product(left, right, target, harness):
    command = [
        sys.executable,
        str(harness / "run.py"),
        "compare",
        "--baseline",
        str(left),
        "--candidate",
        str(right),
        "--output",
        str(target),
    ]
    run = subprocess.run(command, capture_output=True, text=True)
    comparison = (
        json.loads(target.read_text())
        if target.exists()
        else {"status": "invalid", "errors": [run.stderr]}
    )
    return {
        "returncode": run.returncode,
        "comparison": comparison,
        "stdout": run.stdout,
        "stderr": run.stderr,
    }


def diagnostic(cells, record, calibrate, harness, evidence, root):
    DRIVER.validate_cells(cells)
    shutil.copy2(Path(__file__), evidence / "diagnostic-source.py")
    aa, ab = [], []
    for index, cell in enumerate(cells):
        folders = {}
        schedule = order(index)
        DRIVER.save(
            evidence / (cell["id"] + ".window-order.json"),
            {"cell": cell, "schedule": schedule, "qualified": False},
        )
        for side, artifact in schedule:
            folders[side] = record(cell, "diagnostic", side, artifact, harness)
        for role, left, right in [
            ("stock", "base-a", "base-b"),
            ("repair", "repair-a", "repair-b"),
        ]:
            comparison = calibrate(folders[left], folders[right], cell)
            row = {
                "id": cell["id"],
                "source_role": role,
                "comparison": comparison,
                "returncode": 0 if comparison["status"] == "screen-passed" else 1,
            }
            DRIVER.save(evidence / (cell["id"] + "." + role + ".repeatability.json"), row)
            aa.append(row)
        for suffix in ("a", "b"):
            row = product(
                folders["base-" + suffix],
                folders["repair-" + suffix],
                evidence / (cell["id"] + ".product-" + suffix + ".comparison.json"),
                harness,
            )
            row.update(id=cell["id"], order_pair=suffix)
            DRIVER.save(evidence / (cell["id"] + ".product-" + suffix + ".result.json"), row)
            ab.append(row)
    valid = all(
        row["comparison"].get("status") in ("screen-passed", "regression")
        and not row["comparison"].get("errors")
        for row in aa + ab
    )
    DRIVER.save(
        evidence / "diagnostic-summary.json",
        {
            "status": "diagnostic-complete" if valid else "diagnostic-invalid",
            "qualified": False,
            "original_gate": "blocked-by-retained-stock-controls",
            "completed_cells": len(cells),
            "repeatability_pairs": len(aa),
            "product_pairs": len(ab),
            "aa": aa,
            "ab": ab,
        },
    )
    return {
        "status": "diagnostic-complete" if valid else "diagnostic-invalid",
        "qualified": False,
        "aa": aa,
        "ab": ab,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-request", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    request = json.loads(args.run_request.read_text())
    if request != request_spec():
        raise ValueError(
            "diagnostic request differs from frozen sources, original workloads or unchanged limits"
        )
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise ValueError("no retries")
    if os.environ.get("DEXPOT_STAGE_DIAGNOSTIC"):
        raise ValueError("no request instrumentation")
    if (
        sys.platform.startswith("linux")
        and not args.prepare_only
        and os.environ.get("DEXPOT_DISJOINT_CONTROL") != "1"
    ):
        raise ValueError("Linux requires unchanged attested disjoint placement")
    DRIVER.RUN_REQUEST = request
    DRIVER.HEAD = CANDIDATE
    DRIVER.PREPARE_ONLY = args.prepare_only
    try:
        return DRIVER.execute_qualification(diagnostic=diagnostic)
    except BaseException as exc:
        evidence = Path(os.environ["RUNNER_TEMP"]) / "dexpot-socket-runtime-qualification/evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        if not (evidence / "incomplete.json").exists():
            DRIVER.save(
                evidence / "incomplete.json",
                {"status": "diagnostic-incomplete", "qualified": False, "error": repr(exc)},
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
