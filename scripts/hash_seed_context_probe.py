"""Four fixed GIL flat trials: startup-seed sensitivity, not qualification."""

import argparse
import ast
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wrk", required=True)
    args = parser.parse_args()
    root = args.root
    root.mkdir(exist_ok=False)
    original = Path(__file__).parent / "lifecycle_preflight_harness"
    harness = root / "harness"
    shutil.copytree(original, harness)
    before = (harness / "application.py").read_text()
    after = before.replace(
        "import sys\n", "import sys\nfrom context_sidecar import record_context\n", 1
    ).replace("def runtime() -> dict:\n", "def runtime() -> dict:\n    record_context()\n", 1)
    old_functions = {
        n.name: ast.dump(n) for n in ast.parse(before).body if isinstance(n, ast.FunctionDef)
    }
    new_functions = {
        n.name: ast.dump(n) for n in ast.parse(after).body if isinstance(n, ast.FunctionDef)
    }
    assert all(old_functions[n] == new_functions[n] for n in ["flat", "nested", "cpu", "io"])
    (harness / "application.py").write_text(after)
    helper = """import json,os,resource,sys,time
from pathlib import Path

def record_context():
    r=resource.getrusage(resource.RUSAGE_SELF)
    row={'pid':os.getpid(),'epoch':time.time(),'seed':os.environ.get('PYTHONHASHSEED'),
         'hash_randomization':sys.flags.hash_randomization,'gil_enabled':sys._is_gil_enabled(),
         'user_cpu_s':r.ru_utime,'system_cpu_s':r.ru_stime,
         'voluntary_switches':r.ru_nvcsw,'involuntary_switches':r.ru_nivcsw}
    folder=Path('context-probes');folder.mkdir(exist_ok=True)
    with (folder/(str(os.getpid())+'.jsonl')).open('a') as f:f.write(json.dumps(row)+'\\n')
"""
    (harness / "context_sidecar.py").write_text(helper)
    plan = json.loads((original / "plan.json").read_text())
    plan["duration_s"] = 15
    plan["matrix"] = [next(c for c in plan["matrix"] if c["id"] == "gil-flat-1")]
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    protocol = {
        "order": ["0", "1", "1", "0"],
        "scope": "hash-seed sensitivity and context-switch observation; not candidate qualification",
        "duration_s": 15,
        "client_threads": 4,
        "connections": 16,
        "budgets": plan["budgets"],
        "comparison": plan["comparison"],
        "production_or_scheduler_changes": False,
        "timed_handler_asts_unchanged": True,
        "no_retries": True,
        "prediction": "Matched-seed controls must be stable and cross-seed effects consistent to support seed sensitivity; a matched-seed failure rejects seed matching as sufficient.",
        "helper_sha256": hashlib.sha256(helper.encode()).hexdigest(),
        "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "limits": "Context counters include readiness/warmup around the timed interval. Counters are observational, not proof of a GIL or host cause. Seed0 disables hash randomization only in this loopback diagnostic.",
    }
    (root / "predeclared.json").write_text(json.dumps(protocol, indent=2))
    assert (
        protocol["wheel_sha256"]
        == "d49d77422bc34ce94b40d603a4f9c3b49030310bbbc3308b84ea8f4bf5a29cc2"
    )
    api = runpy.run_path(str(harness / "run.py"))
    observations = []
    for index, seed in enumerate(protocol["order"]):
        assert (
            hashlib.sha256((harness / "context_sidecar.py").read_bytes()).hexdigest()
            == protocol["helper_sha256"]
        )
        folder = root / (str(index) + "-seed-" + seed)
        env = dict(os.environ, PYTHONHASHSEED=seed)
        env.pop("PYTHON_GIL", None)
        env.pop("PYTHONPATH", None)
        command = [
            sys.executable,
            str(harness / "run.py"),
            "record",
            "--plan",
            str(plan_path),
            "--python-gil",
            args.python,
            "--wheel",
            str(args.wheel),
            "--wrk",
            args.wrk,
            "--output",
            str(folder),
        ]
        completed = subprocess.run(command, env=env, cwd=root, capture_output=True, text=True)
        assert (
            hashlib.sha256((harness / "context_sidecar.py").read_bytes()).hexdigest()
            == protocol["helper_sha256"]
        )
        (root / (str(index) + ".command.json")).write_text(
            json.dumps(
                {
                    "command": command,
                    "seed": seed,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                indent=2,
            )
        )
        manifest = json.loads((folder / "manifest.json").read_text())
        trial = json.loads((folder / "gil-flat-1.json").read_text())
        control = json.loads((folder / "gil.preflight.json").read_text())
        validation = api["check_recording"](manifest, [trial], {"gil": control})
        pid = trial["runtime"]["pid"]
        contexts = [
            json.loads(line)
            for line in (folder / "context-probes" / (str(pid) + ".jsonl")).read_text().splitlines()
        ]
        assert len(contexts) >= 2 and all(
            c["pid"] == pid
            and c["seed"] == seed
            and c["hash_randomization"] == int(seed != "0")
            and c["gil_enabled"]
            for c in contexts
        )
        start, end = contexts[0], contexts[-1]
        delta = {
            key: end[key] - start[key]
            for key in ["user_cpu_s", "system_cpu_s", "voluntary_switches", "involuntary_switches"]
        }
        metrics = trial.get("metrics")
        good = metrics["good"] if metrics else 0
        normalized = {
            "cpu_us_per_good": (delta["user_cpu_s"] + delta["system_cpu_s"]) * 1e6 / good
            if good
            else None,
            "voluntary_per_1000_good": delta["voluntary_switches"] * 1000 / good if good else None,
            "involuntary_per_1000_good": delta["involuntary_switches"] * 1000 / good
            if good
            else None,
        }
        observations.append(
            {
                "index": index,
                "seed": seed,
                "validation": validation,
                "manifest": manifest,
                "trial": trial,
                "context_delta": delta,
                "normalized": normalized,
            }
        )
        print(index, seed, validation, metrics, normalized, flush=True)
    assert all(
        o["manifest"]["fingerprints"] == observations[0]["manifest"]["fingerprints"]
        for o in observations
    )
    evaluator = runpy.run_path(str(harness / "evaluate.py"))
    comparisons = []
    for a, b in [(0, 3), (1, 2), (0, 1), (3, 2)]:
        valid = all(observations[x]["validation"]["status"] == "baseline-recorded" for x in [a, b])
        comparison = (
            evaluator["compare"](plan, [observations[a]["trial"]], [observations[b]["trial"]])
            if valid
            else {"status": "invalid"}
        )
        comparisons.append(
            {
                "baseline": a,
                "variant": b,
                "seed_direction": observations[b]["seed"] + "/" + observations[a]["seed"],
                "comparison": comparison,
            }
        )
    summary = {"records": observations, "comparisons": comparisons, "candidate_qualified": False}
    (root / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(comparisons, indent=2), flush=True)


if __name__ == "__main__":
    main()
