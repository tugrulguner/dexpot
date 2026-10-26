"""Run six frozen-main HTTP routing ablations; never candidate qualification."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

BASE = "ca4979a6339e533f11ad135bc760aa081f3f60ab"
SCHEDULE = ["original", "bound-shared", "local-proxy", "local-proxy", "bound-shared", "original"]
TRIAL_SECONDS = 30


@contextlib.contextmanager
def strategy_environment(strategy):
    old = os.environ.get("ROUTE_LOOKUP_STRATEGY")
    os.environ["ROUTE_LOOKUP_STRATEGY"] = strategy
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("ROUTE_LOOKUP_STRATEGY", None)
        else:
            os.environ["ROUTE_LOOKUP_STRATEGY"] = old


def result_document(trials):
    return {
        "kind": "same-artifact-routing-ownership-ablation",
        "candidate_qualified": False,
        "trials": trials,
    }


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default="3.14.7t")
    parser.add_argument("--wrk", default=shutil.which("wrk"))
    args = parser.parse_args()
    assert sys.platform == "linux" and os.environ.get("RUNNER_TEMP") and args.wrk
    repo, output = args.repo.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix="routing-http-", dir=os.environ["RUNNER_TEMP"]))
    source = root / "source"
    source.mkdir()
    raw = subprocess.check_output(["git", "archive", BASE], cwd=repo)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(source, filter="data")
    subprocess.run(
        ["uv", "build", "--wheel", str(source), "--out-dir", str(root / "dist")], check=True
    )
    wheel = next((root / "dist").glob("*.whl"))
    shutil.copyfile(wheel, output / wheel.name)
    env = root / "ft"
    subprocess.run(["uv", "venv", "--python", args.python, str(env)], check=True)
    python = env / "bin/python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel), "msgspec==0.22.0"], check=True
    )
    with (output / "runtime-qualification.log").open("x") as log:
        subprocess.run(
            [
                str(python),
                str(repo / "scripts/verify_runtime_mode.py"),
                "--expect",
                "ft",
                "--negative-extension",
            ],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    from placement_probe import prepare_disjoint, validate_placement
    from route_lookup_http_fixture import instrument_application

    wrapped, client, placement = prepare_disjoint(
        {("main", "ft"): python}, Path(args.wrk).resolve(), root, sorted(os.sched_getaffinity(0))
    )
    fixture = root / "fixture"
    shutil.copytree(repo / "scripts/lifecycle_preflight_harness", fixture)
    application = fixture / "application.py"
    application.write_text(instrument_application(application.read_text()))
    for name in ["route_lookup_probe.py", "route_lookup_http_fixture.py"]:
        shutil.copyfile(repo / "scripts" / name, fixture / name)
    files = [
        "application.py",
        "run.py",
        "evaluate.py",
        "validate.lua",
        "route_lookup_probe.py",
        "route_lookup_http_fixture.py",
    ]
    fixture_hashes = {name: sha(fixture / name) for name in files}
    original = json.loads((fixture / "plan.json").read_text())
    cell = next(c for c in original["matrix"] if c["id"] == "ft-mixed-1")
    plan = dict(original, duration_s=TRIAL_SECONDS, matrix=[cell])
    save(output / "plan.json", plan)
    save(
        output / "predeclared.json",
        {
            "kind": "same-artifact-routing-ownership-ablation",
            "source_base": BASE,
            "diagnostic_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "candidate_qualified": False,
            "schedule": SCHEDULE,
            "duration_s": TRIAL_SECONDS,
            "no_retries": True,
            "placement": placement,
            "fixture_hashes": fixture_hashes,
            "wheel_sha256": sha(wheel),
            "plan": plan,
            "scope": "Frozen main only; original/bound-shared/local-proxy and reversed. No candidate/main or enabled qualification.",
        },
    )
    runner = runpy.run_path(str(fixture / "run.py"))
    evaluator = runpy.run_path(str(fixture / "evaluate.py"))
    rows, pairs, serving_pids, error = [], [], set(), None
    try:
        for index, strategy in enumerate(SCHEDULE):
            assert all(sha(fixture / name) == digest for name, digest in fixture_hashes.items())
            folder = output / f"trial-{index}-{strategy}"
            command = [
                sys.executable,
                str(fixture / "run.py"),
                "record",
                "--plan",
                str(output / "plan.json"),
                "--python-ft",
                str(wrapped["main", "ft"]),
                "--wheel",
                str(wheel),
                "--wrk",
                str(client),
                "--output",
                str(folder),
            ]
            with strategy_environment(strategy):
                process = subprocess.run(command, cwd=root, capture_output=True, text=True)
            save(
                output / f"trial-{index}-command.json",
                {
                    "command": command,
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                },
            )
            manifest = (
                json.loads((folder / "manifest.json").read_text())
                if (folder / "manifest.json").exists()
                else None
            )
            trial = (
                json.loads((folder / "ft-mixed-1.json").read_text())
                if (folder / "ft-mixed-1.json").exists()
                else None
            )
            control = (
                json.loads((folder / "ft.preflight.json").read_text())
                if (folder / "ft.preflight.json").exists()
                else None
            )
            validity = (
                runner["check_recording"](manifest, [trial], {"ft": control})
                if manifest and trial and control
                else None
            )
            binding_report = None
            if trial and isinstance(trial.get("runtime"), dict):
                pid = trial["runtime"]["pid"]
                serving_pids.add(pid)
                report_file = folder / "route-probes" / f"report-{pid}.json"
                if report_file.exists():
                    binding_report = json.loads(report_file.read_text())
            if control and isinstance(control.get("runtime"), dict):
                serving_pids.add(control["runtime"]["pid"])
            bindings = (binding_report or {}).get("bindings", [])
            activation = (
                binding_report is not None
                and binding_report["observed_strategy"] == strategy
                and len(bindings) >= plan["connections"]
                and all(
                    b["strategy"] == strategy
                    and b["same_route_values"]
                    and b["closed"]
                    and b["owns_mapping"] is (strategy == "local-proxy")
                    and b["mapping_type"] == "mappingproxy"
                    for b in bindings
                )
                and trial["runtime"].get("route_lookup_strategy") == strategy
            )
            valid = (
                process.returncode == 0
                and validity
                and validity["status"] == "baseline-recorded"
                and activation
                and trial.get("client_resources", {}).get("complete") is True
            )
            row = {
                "index": index,
                "strategy": strategy,
                "valid": bool(valid),
                "recording_validity": validity,
                "activation_pass": activation,
                "binding_report": binding_report,
                "manifest": manifest,
                "trial": trial,
            }
            save(output / f"trial-{index}-result.json", row)
            rows.append(row)
            print("ROUTE_TRIAL", index, strategy, bool(valid), flush=True)
            assert all(sha(fixture / name) == digest for name, digest in fixture_hashes.items())
        for left, right in [(0, 1), (0, 2), (1, 2), (5, 4), (5, 3), (4, 3)]:
            base, candidate = rows[left], rows[right]
            comparison = None
            if base["valid"] and candidate["valid"]:
                keys = [
                    "plan",
                    "platform",
                    "machine",
                    "cpu_count",
                    "psutil",
                    "controller_python",
                    "fingerprints",
                    "runtime",
                ]
                assert all(base["manifest"][key] == candidate["manifest"][key] for key in keys)
                comparison = evaluator["compare"](plan, [base["trial"]], [candidate["trial"]])
            pairs.append(
                {
                    "baseline": left,
                    "variant": right,
                    "ratio_direction": candidate["strategy"] + "/" + base["strategy"],
                    "comparison": comparison,
                }
            )
    except BaseException as exc:
        error = repr(exc)
        raise
    finally:
        attestation = validate_placement(root, placement, serving_pids)
        save(output / "affinity-validation.json", attestation)
        result = result_document(rows)
        result.update(
            status="diagnostic-complete"
            if len(rows) == 6
            and all(r["valid"] for r in rows)
            and attestation["passed"]
            and error is None
            else "diagnostic-invalid",
            expected_trials=6,
            completed_trials=len(rows),
            pairs=pairs,
            error=error,
        )
        save(output / "results.json", result)
        shutil.copytree(root / "placement-launchers", output / "launchers")
    print(json.dumps({k: v for k, v in result.items() if k != "trials"}, indent=2), flush=True)
    return 0 if result["status"] == "diagnostic-complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
