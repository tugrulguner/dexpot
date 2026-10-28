"""Fail-closed AA-then-AB socket runtime-repair qualification orchestration.

No lifecycle-enabled cohort is part of this qualification. Existing harness methods
remain authoritative for builds, runtime guards, recording, validation and comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

BASE = "ca4979a6339e533f11ad135bc760aa081f3f60ab"
HEAD = "58a9730be87142e08309ad68ea101800aaf00ebe"
EXPECTED_COUNT = 12


def validate_cells(cells: list[dict]) -> list[str]:
    raw_ids = [cell.get("id") for cell in cells]
    if len(raw_ids) != EXPECTED_COUNT or any(not isinstance(x, str) or not x for x in raw_ids):
        raise ValueError("the original matrix must contain exactly 12 named cells")
    ids = [str(value) for value in raw_ids]
    if len(set(ids)) != EXPECTED_COUNT:
        raise ValueError("duplicate cell IDs")
    return ids


def cohort_passes(rows: list[dict], expected: list[str]) -> bool:
    if len(rows) != len(expected):
        return False
    ids = [row.get("id") for row in rows]
    return (
        len(set(ids)) == len(expected)
        and set(ids) == set(expected)
        and all(
            row.get("returncode") == 0
            and isinstance(row.get("comparison"), dict)
            and row["comparison"].get("status") == "screen-passed"
            for row in rows
        )
    )


def run_stages(cells: list[dict], pair: Callable, *, controls: bool = False) -> dict:
    """Execute all 12 AA pairs first; AB is unreachable unless every AA validates.

    Each pair callable accepts (cell, cohort, sides, reverse_order). Return rows
    preserve every pair result, including invalid/failing evidence.
    """
    expected = validate_cells(cells)
    aa = []
    for index, cell in enumerate(cells):
        aa.append(pair(cell, "aa", [("left", "base"), ("right", "base")], bool(index % 2)))
    if controls or not cohort_passes(aa, expected):
        return result(aa, [], expected, controls=controls)
    ab = []
    for index, cell in enumerate(cells):
        ab.append(pair(cell, "ab", [("base", "base"), ("candidate", "candidate")], bool(index % 2)))
    return result(aa, ab, expected, controls=controls)


def result(aa: list[dict], ab: list[dict], expected: list[str], *, controls=False) -> dict:
    aa_ok = cohort_passes(aa, expected)
    ab_ok = aa_ok and cohort_passes(ab, expected)
    return {
        "status": "screen-passed"
        if ab_ok and not controls
        else ("screen-failed" if aa_ok else "invalid-control"),
        "qualified": bool(ab_ok and not controls),
        "candidate_qualified": bool(ab_ok and not controls),
        "controls_only": bool(controls),
        "expected_cells": len(expected),
        "completed_aa": len(aa),
        "completed_ab": len(ab),
        "aa": aa,
        "ab": ab,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run-request", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.run_request is None:
        parser.error("--run-request is required")
    global RUN_REQUEST, PREPARE_ONLY
    PREPARE_ONLY = args.prepare_only
    RUN_REQUEST = validate_request(args.run_request)
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise ValueError("this no-retry campaign may run only attempt 1")
    try:
        return execute_qualification()
    except BaseException as exc:
        evidence = (
            Path(os.environ["RUNNER_TEMP"]) / "dexpot-socket-runtime-qualification" / "evidence"
        )
        evidence.mkdir(parents=True, exist_ok=True)
        failure = evidence / "incomplete.json"
        if not failure.exists():
            save(
                failure,
                {
                    "status": "runner-incomplete",
                    "qualified": False,
                    "error": repr(exc),
                    "request": RUN_REQUEST,
                },
            )
        raise


def self_test() -> int:
    cells = [{"id": f"cell-{i}"} for i in range(EXPECTED_COUNT)]

    def good(cell, cohort, sides, reverse):
        return {
            "id": cell["id"],
            "cohort": cohort,
            "returncode": 0,
            "comparison": {"status": "screen-passed"},
        }

    calls = []

    def tracked(*args):
        calls.append(args[1])
        return good(*args)

    out = run_stages(cells, tracked)
    assert out["qualified"] and calls == ["aa"] * 12 + ["ab"] * 12
    failed_calls = []

    def aa_bad(cell, cohort, sides, reverse):
        failed_calls.append(cohort)
        row = good(cell, cohort, sides, reverse)
        if cohort == "aa" and cell["id"] == "cell-7":
            row["comparison"]["status"] = "regression"
        return row

    out = run_stages(cells, aa_bad)
    assert not out["qualified"] and out["completed_aa"] == 12 and not out["ab"]
    assert failed_calls == ["aa"] * 12

    def ab_bad(cell, cohort, sides, reverse):
        row = good(cell, cohort, sides, reverse)
        if cohort == "ab" and cell["id"] == "cell-3":
            row["returncode"] = 1
        return row

    out = run_stages(cells, ab_bad)
    assert not out["qualified"] and out["completed_ab"] == 12
    assert not cohort_passes(out["aa"][:-1], [x["id"] for x in cells])
    assert not cohort_passes(out["aa"] + [out["aa"][0]], [x["id"] for x in cells])
    assert not result(out["aa"], [], [x["id"] for x in cells], controls=True)["qualified"]
    print("socket qualification orchestration self-test passed; synthetic evidence only")
    return 0


RUN_REQUEST = {}
PREPARE_ONLY = False


def validate_request(path: Path) -> dict:
    request = json.loads(path.read_text())
    repo = Path(__file__).resolve().parents[1]
    original = json.loads((repo / "scripts/lifecycle_preflight_harness/plan.json").read_text())
    expected = {
        "schema": 1,
        "kind": "runtime-repair-qualification",
        "base_sha": BASE,
        "candidate_sha": HEAD,
        "matrix_source": "scripts/lifecycle_preflight_harness/plan.json",
        "duration_s": 15,
        "client_threads": original["client_threads"],
        "connections": original["connections"],
        "pool": original["pool"],
        "budgets": original["budgets"],
        "comparison": original["comparison"],
        "sequence": [
            "all_12_AA_pairs_both_directions",
            "only_if_all_AA_pass_all_12_AB_pairs_directional",
        ],
        "no_retries": True,
        "candidate_qualified_from_controls": False,
        "lifecycle_enabled_cohort": False,
        "plan_source_sha256": hashlib.sha256(
            (repo / "scripts/lifecycle_preflight_harness/plan.json").read_bytes()
        ).hexdigest(),
        "reused_driver_sha256": hashlib.sha256(
            (repo / "scripts/controlled_lifecycle_qualification.py").read_bytes()
        ).hexdigest(),
    }
    if request != expected:
        raise ValueError(
            "run request differs from fixed commits, original budgets or stage protocol"
        )
    validate_cells(original["matrix"])
    if os.environ.get("DEXPOT_STAGE_DIAGNOSTIC"):
        raise ValueError(
            "instrumented lifecycle diagnostics are not a runtime repair qualification"
        )
    if (
        sys.platform.startswith("linux")
        and os.environ.get("DEXPOT_DISJOINT_CONTROL") != "1"
        and not PREPARE_ONLY
    ):
        raise ValueError("Linux qualification requires original attested disjoint placement")
    return request


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)


def execute(command, *, cwd=None):
    print("EXEC", command, flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def power_snapshot(governor=Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")):
    if sys.platform == "darwin":
        return {
            "platform": sys.platform,
            "pmset": subprocess.check_output(["pmset", "-g", "custom"], text=True),
        }
    return {
        "platform": sys.platform,
        "cpu0_governor": governor.read_text().strip() if governor.is_file() else None,
    }


def execute_qualification(diagnostic=None):
    repo = Path(__file__).resolve().parents[1]
    root = Path(os.environ["RUNNER_TEMP"]) / "dexpot-socket-runtime-qualification"
    root.mkdir()
    evidence = root / "evidence"
    evidence.mkdir()
    save(evidence / "request.json", RUN_REQUEST)
    shutil.copy2(Path(__file__), evidence / "orchestrator-source.py")
    save(
        evidence / "controller.json",
        {
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "qualified": False,
        },
    )
    stage_diagnostic = False
    sources, wheels, pythons = {}, {}, {}
    for name, sha in (("main", BASE), ("pr", HEAD)):
        source = root / ("source-" + name)
        execute(["git", "worktree", "add", "--detach", str(source), sha], cwd=repo)
        assert (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
            == sha
        )
        dist = root / ("dist-" + name)
        execute(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=source)
        choices = list(dist.glob("*.whl"))
        assert len(choices) == 1
        sources[name], wheels[name] = source, choices[0]
        for mode, version in (("gil", "3.14.7"), ("ft", "3.14.7t")):
            env = root / (name + "-" + mode)
            execute(["uv", "venv", "--python", version, str(env)])
            python = env / "bin/python"
            execute(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    str(wheels[name]),
                    "msgspec==0.22.0",
                ]
            )
            pythons[name, mode] = python
            runtime_command = [
                str(python),
                str(repo / "scripts/verify_runtime_mode.py"),
                "--expect",
                mode,
            ]
            if mode == "ft":
                runtime_command.append("--negative-extension")
            execute(runtime_command, cwd=root)
    if PREPARE_ONLY:
        save(
            evidence / "preparation-only.json",
            {
                "status": "preparation-only",
                "qualified": False,
                "base_sha": BASE,
                "head_sha": HEAD,
                "wheel_sha256": {
                    name: hashlib.sha256(wheel.read_bytes()).hexdigest()
                    for name, wheel in wheels.items()
                },
            },
        )
        print(
            "PREPARATION ONLY: real wheels, four isolated runtimes and guards passed; no timing or qualification"
        )
        return 0
    harness = repo / "scripts/lifecycle_preflight_harness"
    original = json.loads((harness / "plan.json").read_text())
    expected = [cell["id"] for cell in original["matrix"]]
    assert len(expected) == len(set(expected)) == 12
    assert original["comparison"] == {"min_goodput_ratio": 0.9, "max_adjusted_p99_ratio": 1.25}
    wrk = shutil.which("wrk")
    assert wrk
    placement = None
    if os.environ.get("DEXPOT_DISJOINT_CONTROL") == "1":
        if sys.platform != "linux":
            raise RuntimeError("disjoint placement is supported only on Linux")
        from placement_probe import prepare_disjoint

        pythons, wrapped_client, placement = prepare_disjoint(
            pythons, Path(wrk), root, sorted(os.sched_getaffinity(0))
        )
        wrk = str(wrapped_client)
    save(
        evidence / "predeclared.json",
        {
            "base_sha": BASE,
            "head_sha": HEAD,
            "placement": placement,
            "duration_s": 30 if stage_diagnostic else 15,
            "stage_diagnostic_only": stage_diagnostic,
            "original_plan": original,
            "cells": ["ft-mixed-1"] if stage_diagnostic else expected,
            "no_retries": True,
            "schedule": RUN_REQUEST["sequence"]
            if diagnostic is not None
            else "all12 AA first; only if passing all12 AB; reverse side order on odd cell indices",
            "diagnostic_only": diagnostic is not None,
            "lifecycle_enabled_cohort": False,
            "qualification_scope": "original closed-loop numerical/resource screen, not scheduled-arrival SLO proof",
            "request": RUN_REQUEST,
            "decision": "diagnostic only; original qualification remains blocked"
            if diagnostic is not None
            else "all cells pass unchanged numerical and resource budgets",
            "wheel_sha256": {
                k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in wheels.items()
            },
            "validator_sha256": hashlib.sha256((harness / "validate.lua").read_bytes()).hexdigest(),
            "wrk_sha256": hashlib.sha256(Path(wrk).read_bytes()).hexdigest(),
            "runtime": subprocess.check_output(["uname", "-a"], text=True),
            "power_read_only": power_snapshot(),
        },
    )

    def record(cell, cohort, side, artifact, selected_harness):
        plan = evidence / (cell["id"] + "-" + cohort + ".plan.json")
        if not plan.exists():
            save(plan, dict(original, duration_s=30 if stage_diagnostic else 15, matrix=[cell]))
        out = evidence / (cell["id"] + "-" + cohort + "-" + side)
        command = [
            sys.executable,
            str(selected_harness / "run.py"),
            "record",
            "--plan",
            str(plan),
            "--python-gil",
            str(pythons[artifact, "gil"]),
            "--python-ft",
            str(pythons[artifact, "ft"]),
            "--wheel",
            str(wheels[artifact]),
            "--wrk",
            wrk,
            "--output",
            str(out),
        ]
        started = time.time()
        result = subprocess.run(command, capture_output=True, text=True, cwd=root)
        save(
            evidence / (out.name + ".command.json"),
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "started": started,
                "finished": time.time(),
            },
        )
        print(out.name, result.returncode, flush=True)
        return out

    def calibrate(left, right, cell):
        # The candidate CLI intentionally rejects identical artifacts. Calibration
        # instead validates both recordings, then uses its unchanged numeric evaluator.
        runner_api = runpy.run_path(str(harness / "run.py"))
        evaluator = runpy.run_path(str(harness / "evaluate.py"))
        manifests, observations, errors = [], [], []
        try:
            for folder in (left, right):
                manifest = json.loads((folder / "manifest.json").read_text())
                trial = json.loads((folder / (cell["id"] + ".json")).read_text())
                controls = {
                    mode: json.loads((folder / (mode + ".preflight.json")).read_text())
                    for mode in manifest["runtime"]
                }
                validation = runner_api["check_recording"](manifest, [trial], controls)
                errors.extend(validation["errors"])
                manifests.append(manifest)
                observations.append([trial])
            for key in (
                "plan",
                "platform",
                "machine",
                "cpu_count",
                "psutil",
                "controller_python",
                "fingerprints",
                "runtime",
            ):
                if manifests[0][key] != manifests[1][key]:
                    errors.append("A/A inputs differ: " + key)
            if errors:
                return {"status": "invalid", "errors": errors, "pairs": []}
            comparison = evaluator["compare"](manifests[0]["plan"], *observations)
            reverse = evaluator["compare"](manifests[0]["plan"], *observations[::-1])
            # Identical-source controls must be repeatable, not merely avoid a
            # loss in one arbitrary direction. Product comparisons stay directional.
            comparison["reverse_comparison"] = reverse
            comparison["calibration_directionality"] = "both"
            reverse_pairs = {pair["id"]: pair for pair in reverse["pairs"]}
            for pair in comparison["pairs"]:
                pair["forward_passed"] = pair["passed"]
                pair["reverse_passed"] = reverse_pairs.get(pair["id"], {}).get("passed", False)
                pair["passed"] = pair["forward_passed"] and pair["reverse_passed"]
            if "invalid" in (comparison["status"], reverse["status"]):
                comparison["status"] = "invalid"
                comparison["errors"].extend("reverse: " + error for error in reverse["errors"])
            elif reverse["status"] != "screen-passed":
                comparison["status"] = "regression"
            comparison["comparison_kind"] = "identical-artifact-calibration-not-candidate-proof"
            return comparison
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"status": "invalid", "errors": [repr(exc)], "pairs": []}

    def pair(cell, cohort, sides, reverse):
        folders = {}
        for side, artifact, selected_harness in sides[::-1] if reverse else sides:
            folders[side] = record(cell, cohort, side, artifact, selected_harness)
        target = evidence / (cell["id"] + "-" + cohort + ".comparison.json")
        command = [
            sys.executable,
            str(harness / "run.py"),
            "compare",
            "--baseline",
            str(folders[sides[0][0]]),
            "--candidate",
            str(folders[sides[1][0]]),
            "--output",
            str(target),
        ]
        if cohort == "aa":
            comparison = calibrate(folders[sides[0][0]], folders[sides[1][0]], cell)
            save(target, comparison)
            row = {
                "id": cell["id"],
                "returncode": 0 if comparison["status"] == "screen-passed" else 1,
                "comparison": comparison,
                "stdout": "",
                "stderr": "",
            }
        else:
            result = subprocess.run(command, capture_output=True, text=True, cwd=root)
            row = {
                "id": cell["id"],
                "returncode": result.returncode,
                "comparison": json.loads(target.read_text()) if target.exists() else None,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        save(evidence / (cell["id"] + "-" + cohort + ".result.json"), row)
        return row

    def runtime_pair(cell, cohort, sides, reverse):
        roles = {"base": "main", "candidate": "pr"}
        return pair(
            cell, cohort, [(side, roles[artifact], harness) for side, artifact in sides], reverse
        )

    stages = (
        run_stages(original["matrix"], runtime_pair)
        if diagnostic is None
        else diagnostic(original["matrix"], record, calibrate, harness, evidence, root)
    )
    aa, ab = stages["aa"], stages["ab"]
    verdict = stages["status"]
    if diagnostic is not None and verdict == "screen-passed":
        raise RuntimeError("a diagnostic cannot return a qualification verdict")
    if placement is not None:
        from placement_probe import validate_placement

        serving_pids = set()
        for path in evidence.glob("*/*.json"):
            observed_record = json.loads(path.read_text())
            runtime = observed_record.get("runtime")
            if isinstance(runtime, dict) and isinstance(runtime.get("pid"), int):
                serving_pids.add(runtime["pid"])
        attestation = validate_placement(root, placement, serving_pids)
        save(evidence / "affinity-validation.json", attestation)
        if not attestation["passed"]:
            verdict = "invalid-placement"
    save(
        evidence / "results.json",
        {
            "status": verdict,
            "source_base": BASE,
            "source_head": HEAD,
            "expected_cells_each": 2 if stage_diagnostic else 12,
            "diagnostic_only": diagnostic is not None,
            "repeatability_pairs_per_cell": 2 if diagnostic is not None else 1,
            "product_pairs_per_cell": 2 if diagnostic is not None else 1,
            "stage_diagnostic_only": stage_diagnostic,
            "completed_aa": len(aa),
            "completed_ab": len(ab),
            "aa": aa,
            "ab": ab,
            "passed": verdict == "screen-passed",
            "qualified": verdict == "screen-passed",
            "candidate_qualified": verdict == "screen-passed",
        },
    )
    print("FINAL", verdict, flush=True)
    return 0 if verdict in ("screen-passed", "diagnostic-complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
