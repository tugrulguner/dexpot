"""Control-only CPU-overlap probe. Never qualifies a candidate or changes runtime code."""

import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

BASE = "ca4979a6339e533f11ad135bc760aa081f3f60ab"
ROOT = Path(__file__).resolve().parents[1]


def placements(allowed):
    if len(set(allowed)) < 4:
        raise ValueError("four distinct allowed CPUs required")
    ids = sorted(set(allowed))[:4]
    return {
        "overlap": {"server": ids[:2], "client": ids[:2]},
        "disjoint": {"server": ids[:2], "client": ids[2:4]},
    }


def schedule():
    return [
        {"id": f"{mode}-{index}-{placement}", "runtime": mode, "placement": placement}
        for mode in ("gil", "ft")
        for index, placement in enumerate(("overlap", "disjoint", "disjoint", "overlap"))
    ]


def calibration_schedule(matrix):
    return [
        dict(
            id=f"{cell['id']}-{side}",
            runtime=cell["runtime"],
            placement="disjoint",
            side=side,
            cell=cell,
        )
        for index, cell in enumerate(matrix)
        for side in (("left", "right") if index % 2 == 0 else ("right", "left"))
    ]


def calibration_verdict(rows, pairs):
    okay = (
        len(rows) == 24
        and len(pairs) == 12
        and all(r["valid"] for r in rows)
        and all(p.get("comparison") and p["comparison"]["status"] == "screen-passed" for p in pairs)
    )
    return {
        "status": "calibration-only-passed" if okay else "invalid-control",
        "candidate_qualified": False,
    }


def diagnostic_verdict(rows):
    status = "diagnostic-complete"
    if len(rows) != 8:
        status = "diagnostic-incomplete"
    elif not all(row["valid"] for row in rows):
        status = "diagnostic-invalid"
    return {"status": status, "candidate_qualified": False}


def save(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def execute(args, **kwargs):
    print("EXEC", args, flush=True)
    return subprocess.run(args, check=True, **kwargs)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launcher(path, executable, cpus):
    # Every exec records its actual process-local mask, including native client.
    text = (
        "#!/usr/bin/python3\nimport os,sys,json\n"
        f"os.sched_setaffinity(0, {set(cpus)!r})\n"
        f"with open({str(path) + '.launches.jsonl'!r}, 'a') as f:\n"
        " f.write(json.dumps(dict(pid=os.getpid(),affinity=sorted(os.sched_getaffinity(0)),argv=sys.argv[1:]))+'\\n')\n"
        f"os.execv({str(executable)!r}, [{str(executable)!r}, *sys.argv[1:]])\n"
    )
    path.write_text(text)
    path.chmod(0o755)


def prepare_disjoint(pythons, wrk, root, allowed):
    mask = placements(allowed)["disjoint"]
    folder = root / "placement-launchers"
    folder.mkdir()
    wrapped = {}
    for (artifact, mode), binary in pythons.items():
        path = folder / (artifact + "-" + mode)
        launcher(path, binary, mask["server"])
        wrapped[artifact, mode] = path
    client = folder / "native-client"
    launcher(client, wrk, mask["client"])
    metadata = {
        "server_cpus": mask["server"],
        "client_cpus": mask["client"],
        "controller_allowed_cpus": allowed,
        "native_wrk_sha256": sha(wrk),
        "candidate_qualified": False,
        "scope": "process-local masks; no global settings",
    }
    return wrapped, client, metadata


def validate_placement(root, metadata, serving_pids):
    errors, observed, server_pids = [], {}, set()
    for path in (root / "placement-launchers").glob("*.launches.jsonl"):
        client = path.name == "native-client.launches.jsonl"
        expected = metadata["client_cpus" if client else "server_cpus"]
        launches = [json.loads(line) for line in path.read_text().splitlines()]
        observed[path.name] = launches
        if not launches or any(row["affinity"] != expected for row in launches):
            errors.append("missing or wrong mask: " + path.name)
        if not client:
            server_pids.update(row["pid"] for row in launches)
    if not observed or "native-client.launches.jsonl" not in observed:
        errors.append("missing launch attestations")
    if not serving_pids or not serving_pids.issubset(server_pids):
        errors.append("serving PID missing launch attestation")
    return {
        "passed": not errors,
        "errors": errors,
        "observed": observed,
        "serving_pids": sorted(serving_pids),
    }


def main():
    if sys.platform != "linux":
        raise RuntimeError("Linux-only diagnostic; no machine-wide setting changes")
    allowed = sorted(os.sched_getaffinity(0))
    masks = placements(allowed)
    calibration = "--calibration" in sys.argv[1:]
    evidence = Path(os.environ["RUNNER_TEMP"]) / (
        "dexpot-placement-calibration-evidence" if calibration else "dexpot-placement-evidence"
    )
    evidence.mkdir(exist_ok=False)
    harness = ROOT / "scripts/lifecycle_preflight_harness"
    work = evidence / "build"
    work.mkdir()
    source = work / "main-source"
    source.mkdir()
    raw = subprocess.check_output(["git", "archive", BASE], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(source, filter="data")
    execute(["uv", "build", str(source), "--out-dir", str(work / "dist")])
    wheel = next((work / "dist").glob("*.whl"))
    interpreters = {}
    for mode, version in (("gil", "3.14.7"), ("ft", "3.14.7t")):
        env = work / mode
        execute(["uv", "venv", "--python", version, str(env)])
        python = env / "bin/python"
        execute(["uv", "pip", "install", "--python", str(python), str(wheel), "msgspec==0.22.0"])
        command = [str(python), str(ROOT / "scripts/verify_runtime_mode.py"), "--expect", mode]
        if mode == "ft":
            command.append("--negative-extension")
        with (evidence / f"{mode}-runtime.log").open("x") as log:
            execute(command, cwd=evidence, stdout=log, stderr=subprocess.STDOUT)
        interpreters[mode] = python
    wrk = Path(shutil.which("wrk"))
    original = json.loads((harness / "plan.json").read_text())
    selected_schedule = calibration_schedule(original["matrix"]) if calibration else schedule()
    manifest = {
        "kind": "disjoint-full-control-calibration-not-candidate-qualification"
        if calibration
        else "CPU-overlap-control-diagnostic-not-qualification",
        "base_sha": BASE,
        "diagnostic_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "hypothesis": "Separating client and server CPUs at equal two-CPU process budgets reduces competition; retain both adverse and invalid results.",
        "schedule": selected_schedule,
        "allowed_controller_cpus": allowed,
        "placements": masks,
        "duration_s": 15,
        "no_retries": True,
        "candidate_qualified": False,
        "original_plan": original,
        "wheel_sha256": sha(wheel),
        "native_wrk_sha256": sha(wrk),
        "validator_sha256": sha(harness / "validate.lua"),
        "runner_sha256": sha(harness / "run.py"),
        "evaluator_sha256": sha(harness / "evaluate.py"),
        "governor": Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        .read_text()
        .strip()
        if Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").exists()
        else None,
    }
    save(evidence / "predeclared.json", manifest)
    wrappers = work / "wrappers"
    wrappers.mkdir()
    rows = []
    for item in selected_schedule:
        trial_root = evidence / item["id"]
        trial_root.mkdir()
        mask = masks[item["placement"]]
        python_wrapper = wrappers / (item["runtime"] + "-" + item["placement"] + "-python")
        client_wrapper = wrappers / (item["placement"] + "-wrk")
        if not python_wrapper.exists():
            launcher(python_wrapper, interpreters[item["runtime"]], mask["server"])
        if not client_wrapper.exists():
            launcher(client_wrapper, wrk, mask["client"])
        cell = item.get("cell") or {
            "id": f"{item['runtime']}-flat-0",
            "runtime": item["runtime"],
            "profile": "flat",
            "repeat": 0,
        }
        plan = dict(original, duration_s=15, matrix=[cell])
        save(trial_root / "plan.json", plan)
        output = trial_root / "recording"
        command = [
            sys.executable,
            str(harness / "run.py"),
            "record",
            "--plan",
            str(trial_root / "plan.json"),
            "--python-" + item["runtime"],
            str(python_wrapper),
            "--wheel",
            str(wheel),
            "--wrk",
            str(client_wrapper),
            "--output",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, cwd=evidence)
        save(
            trial_root / "command.json",
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        report_path = output / "report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        observed_masks = {}
        masks_ok = True
        for label, wrapper in (("server", python_wrapper), ("client", client_wrapper)):
            path = Path(str(wrapper) + ".launches.jsonl")
            launches = (
                [json.loads(line) for line in path.read_text().splitlines()]
                if path.exists()
                else []
            )
            observed_masks[label] = launches
            masks_ok = (
                masks_ok and bool(launches) and all(x["affinity"] == mask[label] for x in launches)
            )
        trial_path = output / (cell["id"] + ".json")
        trial = json.loads(trial_path.read_text()) if trial_path.exists() else None
        masks_ok = (
            masks_ok
            and trial is not None
            and any(
                launch["pid"] == trial.get("runtime", {}).get("pid")
                for launch in observed_masks["server"]
            )
        )
        row = dict(
            item,
            valid=result.returncode == 0
            and report is not None
            and report["status"] == "baseline-recorded"
            and masks_ok,
            effective_masks=observed_masks,
            report=report,
            trial=trial,
        )
        save(trial_root / "result.json", row)
        rows.append(row)
        print("OBSERVED", item["id"], row["valid"], flush=True)
    evaluator = runpy.run_path(str(harness / "evaluate.py"))
    pairs = []
    if calibration:
        for cell in original["matrix"]:
            group = {r["side"]: r for r in rows if r["cell"] == cell}
            left, right = group["left"], group["right"]
            comparison = None
            if left["valid"] and right["valid"]:
                left_manifest = json.loads(
                    (evidence / left["id"] / "recording/manifest.json").read_text()
                )
                right_manifest = json.loads(
                    (evidence / right["id"] / "recording/manifest.json").read_text()
                )
                keys = (
                    "plan",
                    "platform",
                    "machine",
                    "cpu_count",
                    "psutil",
                    "controller_python",
                    "fingerprints",
                    "runtime",
                )
                if all(left_manifest[k] == right_manifest[k] for k in keys):
                    comparison = evaluator["compare"](
                        dict(original, duration_s=15, matrix=[cell]),
                        [left["trial"]],
                        [right["trial"]],
                    )
                else:
                    comparison = {"status": "invalid", "errors": ["A/A inputs differ"], "pairs": []}
            pairs.append({"id": cell["id"], "comparison": comparison})
    for mode in () if calibration else ("gil", "ft"):
        group = [row for row in rows if row["runtime"] == mode]
        for left, right in ((0, 1), (3, 2)):
            control, diagnostic = group[left], group[right]
            comparison = None
            if control["valid"] and diagnostic["valid"]:
                cell = control["trial"]["cell"]
                comparison = evaluator["compare"](
                    dict(original, duration_s=15, matrix=[cell]),
                    [control["trial"]],
                    [diagnostic["trial"]],
                )
            pairs.append(
                {
                    "overlap": control["id"],
                    "disjoint": diagnostic["id"],
                    "ratio_direction": "disjoint/overlap",
                    "comparison": comparison,
                }
            )
    final = dict(
        calibration_verdict(rows, pairs) if calibration else diagnostic_verdict(rows),
        rows=rows,
        pairs=pairs,
        scope="Full original 12-cell A/A under disjoint two-CPU process masks; candidate and lifecycle-enabled cohorts not run."
        if calibration
        else "Two order-reversed pairs per runtime, flat workload only; not a complete calibration cohort, lifecycle or candidate qualification.",
    )
    save(evidence / "results.json", final)
    print(json.dumps({k: v for k, v in final.items() if k != "rows"}, indent=2), flush=True)
    return 0 if final["status"] in ("diagnostic-complete", "calibration-only-passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
