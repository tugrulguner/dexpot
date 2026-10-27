"""Three fixed same-PID windows; only middle window externally traced. Not qualification."""

import argparse
import contextlib
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from trace_target_export import export_targets

WHEEL = "d49d77422bc34ce94b40d603a4f9c3b49030310bbbc3308b84ea8f4bf5a29cc2"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wrk", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    root.mkdir(exist_ok=False)
    public = root / "public"
    public.mkdir()
    original = Path(__file__).parent / "lifecycle_preflight_harness"
    harness = public / "harness"
    shutil.copytree(original, harness)
    api = runpy.run_path(str(harness / "run.py"))
    plan = json.loads((original / "plan.json").read_text())
    plan["duration_s"] = 15
    cell = next(c for c in plan["matrix"] if c["id"] == "gil-flat-1")
    plan["matrix"] = [cell]
    plan_path = public / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    assert hashlib.sha256(args.wheel.read_bytes()).hexdigest() == WHEEL
    (public / "predeclared.json").write_text(
        json.dumps(
            {
                "windows": ["untraced-before", "system-trace", "untraced-after"],
                "server_lifecycles": 1,
                "duration_s": 15,
                "seed": "1",
                "native_client": "unchanged binary, original validator and configuration",
                "application": "unchanged original workload, no request hooks",
                "scope": "component localization only, not qualification; no retries",
                "stop": "No attribution without actual target state transitions and temporal support. Unknowns stay unknown. Profiling may perturb execution; brackets do not prove absence of perturbation.",
                "raw_all_processes_trace_uploaded": False,
            },
            indent=2,
        )
    )
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
        plan=plan_path, wheel=args.wheel, wrk=args.wrk, identities={"gil": identity}
    )
    frozen = api["fingerprints"](config)
    (public / "inputs.json").write_text(
        json.dumps({"runtime": identity, "fingerprints": frozen}, indent=2)
    )
    preflight = api["preflight"](
        args.python, env, public / "preflight.log", identity, "gil", frozen
    )
    (public / "preflight.json").write_text(json.dumps(preflight, indent=2))
    assert all(preflight[k] is True for k in ["churn_pass", "overload_pass", "cleanup_pass"])
    real_server = api["server"]
    all_clients = []
    windows = []
    trace = root / "scheduler.trace"
    with real_server(args.python, env, public / "server.log") as (server, port, state):

        @contextlib.contextmanager
        def persistent(python, env, log):
            assert server.poll() is None
            status, body = api["request"](port, "/runtime")
            assert status == 200 and json.loads(body) == state["runtime"]
            yield server, port, state

        api["trial"].__globals__["server"] = persistent
        for index in range(3):
            tracer = None
            marker = None
            clients = []
            real_popen = subprocess.Popen
            if index == 1:
                key = "io.modepot.dexpot.scheduler." + str(os.getpid())
                marker = real_popen(
                    ["/usr/bin/notifyutil", "-1", key],
                    stdout=(public / "notification.log").open("w"),
                    stderr=subprocess.STDOUT,
                )
                time.sleep(0.1)
                tracer = real_popen(
                    [
                        "sudo",
                        "-n",
                        "xcrun",
                        "xctrace",
                        "record",
                        "--template",
                        "System Trace",
                        "--all-processes",
                        "--time-limit",
                        "30s",
                        "--notify-tracing-started",
                        key,
                        "--no-prompt",
                        "--output",
                        str(trace),
                    ],
                    stdout=(public / "record.log").open("w"),
                    stderr=subprocess.STDOUT,
                )
                try:
                    assert marker.wait(timeout=90) == 0
                except BaseException:
                    marker.terminate()
                    marker.wait()
                    tracer.wait(timeout=180)
                    raise
                (public / "tracing-ready.json").write_text(
                    json.dumps({"wall_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns()})
                )

            def tracked_popen(*a, _real_popen=real_popen, _clients=clients, **kw):
                command = a[0] if a else kw["args"]
                before = {"wall_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns()}
                child = _real_popen(*a, **kw)
                if isinstance(command, (list, tuple)) and str(command[0]) == str(args.wrk):
                    _clients.append(
                        {
                            "pid": child.pid,
                            "argv": list(map(str, command)),
                            "launch_before": before,
                            "launch_after": {
                                "wall_ns": time.time_ns(),
                                "monotonic_ns": time.monotonic_ns(),
                            },
                        }
                    )
                return child

            out = public / ("window-" + str(index))
            out.mkdir()
            try:
                subprocess.Popen = tracked_popen
                row = api["trial"](cell, plan, args.python, env, out, config, frozen)
            finally:
                subprocess.Popen = real_popen
                if tracer is not None:
                    assert tracer.wait(timeout=180) == 0
            assert row["runtime"]["pid"] == server.pid
            assert row["cleanup_pass"] is False
            metrics = row.get("metrics")
            valid = (
                row.get("error") is None
                and row.get("client_returncode") == 0
                and metrics is not None
            )
            if metrics is not None:
                valid = (
                    valid
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
            windows.append(
                {
                    "index": index,
                    "server_pid": server.pid,
                    "window_checks_pass": valid,
                    "clients": clients,
                    "raw": row,
                }
            )
            all_clients.extend(c["pid"] for c in clients)
            (public / "windows.json").write_text(json.dumps(windows, indent=2))
            print("WINDOW", index, row.get("metrics"), flush=True)
    assert state["cleanup_pass"] is True
    target_pids = {server.pid, *(c["pid"] for c in windows[1]["clients"])}
    subprocess.run(
        ["sudo", "-n", "chown", "-R", str(os.getuid()) + ":" + str(os.getgid()), str(trace)],
        check=True,
    )
    exported = export_targets(trace, root / "private-exports", public / "target-trace", target_pids)
    summary = {
        "scope": "one correlated trace bracketed by two untraced same-PID windows; not qualification",
        "server_pid": server.pid,
        "server_cleanup_pass": state["cleanup_pass"],
        "windows": windows,
        "target_pids": sorted(target_pids),
        "export": exported,
        "candidate_qualified": False,
    }
    (public / "summary.json").write_text(json.dumps(summary, indent=2))
    print(
        json.dumps(
            {
                "status": "diagnostic-collected",
                "server_cleanup_pass": state["cleanup_pass"],
                "export": exported,
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
