"""One predeclared runner campaign; no retries, budget changes, or runtime patches."""

import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = "ca4979a6339e533f11ad135bc760aa081f3f60ab"
HEAD = "9753cb95ab2e66b8cdc7920032c570551ee4e7d4"


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)


def execute(command, *, cwd=None):
    print("EXEC", command, flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def passed(rows, expected):
    return (
        len(rows) == len(expected)
        and {row["id"] for row in rows} == set(expected)
        and all(
            row.get("comparison") and row["comparison"]["status"] == "screen-passed" for row in rows
        )
    )


def decide(aa, ab, enabled, expected):
    if not passed(aa, expected):
        return "invalid-control"
    if not passed(ab, expected):
        return "screen-failed"
    if enabled is None:
        return "lifecycle-not-yet-qualified"
    return "screen-passed" if passed(enabled, expected) else "screen-failed"


def self_test():
    good = [{"id": "one", "comparison": {"status": "screen-passed"}}]
    bad = [{"id": "one", "comparison": {"status": "screen-failed"}}]
    assert decide(good, good, good, ["one"]) == "screen-passed"
    assert decide(bad, good, good, ["one"]) == "invalid-control"
    assert decide(good, bad, good, ["one"]) == "screen-failed"
    assert decide(good, good, None, ["one"]) == "lifecycle-not-yet-qualified"
    assert decide(good, good, bad, ["one"]) == "screen-failed"
    assert decide([], good, good, ["one"]) == "invalid-control"
    assert not passed(good * 2, ["one"])
    print("orchestration verdict self-test passed (not benchmark evidence)")


def main():
    repo = Path(__file__).resolve().parents[1]
    root = Path(os.environ["RUNNER_TEMP"]) / "dexpot-lifecycle-qualification"
    root.mkdir()
    evidence = root / "evidence"
    evidence.mkdir()
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
    harness = sources["pr"] / "benchmarks/regression"
    original = json.loads((harness / "plan.json").read_text())
    expected = [cell["id"] for cell in original["matrix"]]
    assert len(expected) == len(set(expected)) == 12
    assert original["comparison"] == {"min_goodput_ratio": 0.9, "max_adjusted_p99_ratio": 1.25}
    wrk = shutil.which("wrk")
    assert wrk
    save(
        evidence / "predeclared.json",
        {
            "base_sha": BASE,
            "head_sha": HEAD,
            "duration_s": 15,
            "original_plan": original,
            "cells": expected,
            "no_retries": True,
            "schedule": "each cell: AA then AB; reverse side order on odd cell indices",
            "enabled_condition": "all 12 AA and all 12 AB pass; otherwise not qualified",
            "enabled_schedule": "all 12 enabled/main pairs, same reversed order",
            "decision": "all cells pass unchanged numerical and resource budgets",
            "wheel_sha256": {
                k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in wheels.items()
            },
            "validator_sha256": hashlib.sha256((harness / "validate.lua").read_bytes()).hexdigest(),
            "wrk_sha256": hashlib.sha256(Path(wrk).read_bytes()).hexdigest(),
            "runtime": subprocess.check_output(["uname", "-a"], text=True),
            "power_read_only": subprocess.check_output(["pmset", "-g", "custom"], text=True),
        },
    )
    enabled_harness = root / "enabled-harness"
    shutil.copytree(harness, enabled_harness)
    application = enabled_harness / "application.py"
    text = application.read_text()
    addition = """from contextlib import contextmanager

@contextmanager
def _qualification_resource():
    print("QUALIFICATION_RESOURCE_ENTER", os.getpid(), flush=True)
    try:
        yield object()
    finally:
        print("QUALIFICATION_RESOURCE_EXIT", os.getpid(), flush=True)

_supports_lifespan = hasattr(app, "lifespan")
if _supports_lifespan:
    app.lifespan(_qualification_resource)
"""
    assert text.count("app = Dex()") == 1
    text = text.replace("app = Dex()", "app = Dex()\n\n" + addition)
    assert text.count('    app.serve("127.0.0.1", args.port)') == 1
    text = text.replace(
        '    app.serve("127.0.0.1", args.port)',
        "    if _supports_lifespan:\n"
        '        app.serve("127.0.0.1", args.port)\n'
        "    else:\n"
        "        with _qualification_resource():\n"
        '            app.serve("127.0.0.1", args.port)',
    )
    application.write_text(text)
    save(
        evidence / "enabled-harness.json",
        {
            "application_sha256": hashlib.sha256(application.read_bytes()).hexdigest(),
            "scope": "context lifetime only; unchanged request handlers and validator",
        },
    )

    def record(cell, cohort, side, artifact, selected_harness):
        plan = evidence / (cell["id"] + "-" + cohort + ".plan.json")
        if not plan.exists():
            save(plan, dict(original, duration_s=15, matrix=[cell]))
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
        if cohort == "enabled":
            log = folders["enabled"] / (cell["id"] + ".server.log")
            content = log.read_text() if log.exists() else ""
            lifecycle_ok = (
                content.count("QUALIFICATION_RESOURCE_ENTER ") == 1
                and content.count("QUALIFICATION_RESOURCE_EXIT ") == 1
            )
            row["lifecycle_markers_pass"] = lifecycle_ok
            if not lifecycle_ok:
                row["comparison"] = None
        save(evidence / (cell["id"] + "-" + cohort + ".result.json"), row)
        return row

    aa, ab = [], []
    for index, cell in enumerate(original["matrix"]):
        aa.append(
            pair(
                cell, "aa", [("left", "main", harness), ("right", "main", harness)], bool(index % 2)
            )
        )
        ab.append(
            pair(cell, "ab", [("main", "main", harness), ("pr", "pr", harness)], bool(index % 2))
        )
    enabled = None
    if passed(aa, expected) and passed(ab, expected):
        enabled = [
            pair(
                cell,
                "enabled",
                [("main", "main", enabled_harness), ("enabled", "pr", enabled_harness)],
                bool(index % 2),
            )
            for index, cell in enumerate(original["matrix"])
        ]
    verdict = decide(aa, ab, enabled, expected)
    save(
        evidence / "results.json",
        {
            "status": verdict,
            "source_base": BASE,
            "source_head": HEAD,
            "expected_cells_each": 12,
            "aa": aa,
            "ab": ab,
            "enabled": enabled,
            "passed": verdict == "screen-passed",
        },
    )
    print("FINAL", verdict, flush=True)
    return 0 if verdict == "screen-passed" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        raise SystemExit(main())
