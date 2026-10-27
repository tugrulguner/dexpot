"""Four windows in ONE server lifecycle; diagnostic, never qualification."""

import argparse
import ast
import contextlib
import hashlib
import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace


def context_helper_source():
    tree = ast.parse((Path(__file__).parent / "hash_seed_context_probe.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assignment = next(
        n
        for n in main.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "helper" for t in n.targets)
    )
    return ast.literal_eval(assignment.value)


def shared_server(api, process, port, state):
    @contextlib.contextmanager
    def scope(python, env, log):
        if process.poll() is not None:
            raise RuntimeError("persistent server exited before window")
        status, body = api["request"](port, "/runtime")
        if status != 200 or json.loads(body) != state["runtime"]:
            raise RuntimeError("persistent server identity changed")
        yield process, port, state
        # Only the real outer server scope may perform/claim teardown.

    return scope


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
    path = harness / "application.py"
    before = path.read_text()
    after = before.replace(
        "import sys\n", "import sys\nfrom context_sidecar import record_context\n", 1
    ).replace("def runtime() -> dict:\n", "def runtime() -> dict:\n    record_context()\n", 1)
    before_functions = {
        n.name: ast.dump(n) for n in ast.parse(before).body if isinstance(n, ast.FunctionDef)
    }
    after_functions = {
        n.name: ast.dump(n) for n in ast.parse(after).body if isinstance(n, ast.FunctionDef)
    }
    assert all(before_functions[n] == after_functions[n] for n in ["flat", "nested", "cpu", "io"])
    path.write_text(after)
    (harness / "context_sidecar.py").write_text(context_helper_source())
    plan = json.loads((original / "plan.json").read_text())
    plan["duration_s"] = 15
    cell = next(c for c in plan["matrix"] if c["id"] == "gil-flat-1")
    plan["matrix"] = [cell]
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    helper_hash = hashlib.sha256((harness / "context_sidecar.py").read_bytes()).hexdigest()
    wheel_hash = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    assert wheel_hash == "d49d77422bc34ce94b40d603a4f9c3b49030310bbbc3308b84ea8f4bf5a29cc2"
    protocol = {
        "helper_sha256": helper_hash,
        "wheel_sha256": wheel_hash,
        "windows": 4,
        "duration_s": 15,
        "seed": "1",
        "server_lifecycles": 1,
        "scope": "same-PID diagnostic windows, not standalone baseline recordings or qualification",
        "prediction": "Variation within one server rules out fresh-server startup/hash/address changes as necessary; stable windows only narrow the search.",
        "limits": "Native client restarts and host scheduling remain variable. Cleanup occurs ONCE after all windows; raw per-window cleanup flags remain false.",
        "budgets": plan["budgets"],
        "comparison_limits_unchanged": plan["comparison"],
        "no_retries": True,
    }
    (root / "predeclared.json").write_text(json.dumps(protocol, indent=2))
    api = runpy.run_path(str(harness / "run.py"))
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DEXPOT_") and k not in ("PYTHON_GIL", "PYTHONPATH")
    }
    env.update(
        DEXPOT_WORKERS="1",
        DEXPOT_HTTP_PARSER="python",
        DEXPOT_POOL="16",
        DEXPOT_MAX_QUEUE="16",
        DEXPOT_MAX_CONNECTIONS="32",
        PYTHONHASHSEED="1",
        PYTHONUNBUFFERED="1",
    )
    identity = json.loads(
        subprocess.check_output(
            [args.python, "-c", api["PROBE"], str(args.wheel)], env=env, text=True
        )
    )
    assert identity["gil_enabled"] is True and identity["ft_build"] is False
    config = SimpleNamespace(
        plan=plan_path, wheel=args.wheel, wrk=Path(args.wrk), identities={"gil": identity}
    )
    frozen = api["fingerprints"](config)
    (root / "inputs.json").write_text(
        json.dumps({"fingerprints": frozen, "runtime": identity}, indent=2)
    )
    preflight = api["preflight"](args.python, env, root / "preflight.log", identity, "gil", frozen)
    (root / "preflight.json").write_text(json.dumps(preflight, indent=2))
    assert all(preflight[k] is True for k in ["churn_pass", "overload_pass", "cleanup_pass"])
    live = root / "live"
    live.mkdir()
    real_server = api["server"]
    observations = []
    with real_server(args.python, env, live / "server.log") as (process, port, state):
        assert state["runtime"]["pid"] == process.pid
        api["trial"].__globals__["server"] = shared_server(api, process, port, state)
        context_path = live / "context-probes" / (str(process.pid) + ".jsonl")
        for index in range(4):
            assert (
                hashlib.sha256((harness / "context_sidecar.py").read_bytes()).hexdigest()
                == helper_hash
            )
            start_index = len(context_path.read_text().splitlines())
            out = root / ("window-" + str(index))
            out.mkdir()
            row = api["trial"](cell, plan, args.python, env, out, config, frozen)
            contexts = [
                json.loads(line) for line in context_path.read_text().splitlines()[start_index:]
            ]
            assert len(contexts) >= 2 and all(
                c["pid"] == process.pid
                and c["seed"] == "1"
                and c["hash_randomization"] == 1
                and c["gil_enabled"]
                for c in contexts
            )
            assert row["runtime"]["pid"] == process.pid
            assert row["cleanup_pass"] is False, "never claim per-window lifecycle cleanup"
            delta = {
                k: contexts[-1][k] - contexts[0][k]
                for k in [
                    "user_cpu_s",
                    "system_cpu_s",
                    "voluntary_switches",
                    "involuntary_switches",
                ]
            }
            metrics = row.get("metrics")
            valid = (
                row["error"] is None
                and row["client_returncode"] == 0
                and metrics is not None
                and metrics["good"] == metrics["requests"]
                and all(
                    metrics[k] == 0
                    for k in [
                        "bad",
                        "connect_errors",
                        "read_errors",
                        "write_errors",
                        "timeout_errors",
                    ]
                )
            )
            valid = (
                valid
                and row["resources"].get("complete") is True
                and all(
                    row["resources"][k] <= plan["budgets"][k]
                    for k in ["rss_bytes", "threads", "fds", "cpu_cores"]
                )
            )
            observations.append(
                {
                    "index": index,
                    "pid": process.pid,
                    "window_checks_pass": valid,
                    "raw": row,
                    "context_delta": delta,
                }
            )
            print("WINDOW", index, process.pid, valid, metrics, delta, flush=True)
    assert state["cleanup_pass"] is True
    result = {
        "scope": protocol["scope"],
        "server_pid": process.pid,
        "server_lifecycle_cleanup_pass": state["cleanup_pass"],
        "windows": observations,
        "candidate_qualified": False,
    }
    (root / "summary.json").write_text(json.dumps(result, indent=2))
    print(
        "TERMINAL: same PID, four windows, one verified final cleanup; no qualification claim",
        flush=True,
    )


if __name__ == "__main__":
    main()
