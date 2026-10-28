"""Same-PID classic versus shared I/O ownership diagnostic; not stock qualification."""

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

import psutil


def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    harness = root / "harness"
    shutil.copytree(Path(args.harness).resolve(), harness)
    api = runpy.run_path(str(harness / "run.py"))
    plan = json.loads((harness / "plan.json").read_text())
    assert plan["client_threads"] == 4 and plan["connections"] == 16 and plan["pool"] == 16
    cell_id = {"flat": "gil-flat-0", "mixed": "gil-mixed-1"}[args.profile]
    cell = next(c for c in plan["matrix"] if c["id"] == cell_id)
    plan.update(duration_s=15, matrix=[cell])
    pp = root / "plan.json"
    pp.write_text(json.dumps(plan, indent=2))
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DEXPOT_") and k not in ("PYTHONPATH", "PYTHON_GIL")
    }
    env.update(
        DEXPOT_WORKERS="1",
        DEXPOT_HTTP_PARSER="python",
        DEXPOT_POOL="16",
        DEXPOT_MAX_QUEUE="16",
        DEXPOT_MAX_CONNECTIONS="32",
        PYTHONUNBUFFERED="1",
        PYTHONPATH=str(Path(args.collector).resolve()),
    )
    python = str(Path(args.python).absolute())
    wheel = Path(args.wheel).resolve()
    identity = json.loads(
        subprocess.check_output([python, "-c", api["PROBE"], str(wheel)], env=env, text=True)
    )
    assert identity["gil_enabled"] and not identity["ft_build"]
    config = SimpleNamespace(
        plan=pp, wheel=wheel, wrk=Path(args.wrk).resolve(), identities={"gil": identity}
    )
    fp = api["fingerprints"](config)
    protocol = {
        "scope": "one artifact and serving PID, classic/shared/shared/classic for future connections; an idle shared owner remains allocated in classic mode; NOT an original-stock comparison or qualification",
        "modes": [False, True, True, False],
        "duration_s": 15,
        "profile": cell["profile"],
        "client_threads": 4,
        "connections": 16,
        "budgets": plan["budgets"],
        "comparison": plan["comparison"],
        "no_retries": True,
        "qualified": False,
        "fingerprints": fp,
        "hook_sha256": hashlib.sha256(
            (Path(args.collector) / "sitecustomize.py").read_bytes()
        ).hexdigest(),
        "prediction": "Does shared I/O ownership itself add material end-to-end cost within one process? Stable controls required; classic path is same-artifact raw-worker mode, not original stock. No OS/GIL attribution.",
    }
    if args.control_only:
        protocol.update(modes=[], control_only=True)
    (root / "predeclared.json").write_text(json.dumps(protocol, indent=2))
    rows = []
    state = {}

    def read_control(port, path):
        status, body = api["request"](port, path)
        return status, json.loads(body)

    def quiescent(port):
        until = time.monotonic() + 5
        while True:
            status, value = read_control(port, "/_wake_diag/status")
            if status == 200 and value["active"] == 1 and value["queued"] == 0:
                return value
            if time.monotonic() > until:
                raise AssertionError("prior workload did not quiesce")
            time.sleep(0.02)

    def configure(port, mode):
        until = time.monotonic() + 5
        while True:
            status, value = read_control(port, "/_wake_diag/" + ("on" if mode else "off"))
            if status == 200:
                return value
            if status != 409 or time.monotonic() > until:
                raise AssertionError("control transition did not quiesce")
            time.sleep(0.02)

    try:
        with api["server"](python, env, root / "server.log") as (process, port, state):
            runtime = state["runtime"]
            api["verify_runtime"](runtime, identity, "gil")
            assert runtime["pid"] == process.pid
            # Exercise both transitions and fence them before the first timed window.
            transitions = []
            for mode in (False, True, False):
                quiescent(port)
                ack = configure(port, mode)
                assert ack["mode"] is mode and ack["pid"] == process.pid
                proof = quiescent(port)
                assert proof["connection_owned"] is mode
                transitions.append({"ack": ack, "future_connection": proof})
            (root / "control-preflight.json").write_text(json.dumps(transitions, indent=2))
            for index, mode in enumerate(protocol["modes"]):
                directory = root / f"trial-{index}"
                directory.mkdir()
                quiescent(port)
                before = configure(port, mode)
                assert before["mode"] is mode and before["pid"] == process.pid
                assert before["active"] == 1 and before["queued"] == 0
                before = quiescent(port)
                assert before["connection_owned"] is mode
                command = [
                    str(config.wrk),
                    "-t",
                    "4",
                    "-c",
                    "16",
                    "-d",
                    "15s",
                    "--latency",
                    "-s",
                    str(harness / "validate.lua"),
                    f"http://127.0.0.1:{port}",
                    "--",
                    cell["profile"],
                ]
                row = {
                    "cell": cell,
                    "fingerprints": fp,
                    "runtime": runtime,
                    "mode": mode,
                    "before": before,
                    "command": command,
                    "metrics": None,
                    "resources": {"complete": False},
                    "error": None,
                    "cleanup_pass": False,
                    "client_returncode": None,
                }
                observer = api["ChildrenObserver"]()
                samples = []
                client_samples = []
                client = None
                try:
                    monitor = psutil.Process(process.pid)
                    samples.append(api["snapshot"](monitor, observer))
                    client = subprocess.Popen(
                        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
                    )
                    until = time.monotonic() + 30
                    client_monitor = psutil.Process(client.pid)
                    while client.poll() is None and time.monotonic() < until:
                        samples.append(api["snapshot"](monitor, observer))
                        with contextlib.suppress(psutil.NoSuchProcess):
                            try:
                                client_samples.append(api["snapshot"](client_monitor, observer))
                            except psutil.AccessDenied:
                                if client.poll() is None:
                                    raise
                        time.sleep(0.1)
                    if client.poll() is None:
                        raise TimeoutError("native client exceeded frozen deadline")
                except Exception as error:
                    row["error"] = repr(error)
                finally:
                    if client is not None:
                        if client.poll() is None:
                            client.kill()
                        stdout, stderr = client.communicate(timeout=3)
                        row.update(
                            stdout=stdout, stderr=stderr, client_returncode=client.returncode
                        )
                        try:
                            row["metrics"] = api["parse_metrics"](stdout, cell["profile"])
                        except Exception as error:
                            row["metrics_error"] = repr(error)
                    row["resources"] = api["resources"](samples)
                    row["client_resources"] = api["resources"](client_samples)
                    observer.close()
                    (directory / "record.json").write_text(json.dumps(row, indent=2))
                assert row["error"] is None and row["client_returncode"] == 0
                metrics = row["metrics"]
                assert metrics is not None
                assert all(
                    metrics[k] == 0
                    for k in [
                        "bad",
                        "connect_errors",
                        "read_errors",
                        "write_errors",
                        "timeout_errors",
                    ]
                )
                assert row["resources"]["complete"] and all(
                    row["resources"][k] <= v for k, v in plan["budgets"].items()
                )
                after = quiescent(port)
                assert (
                    after["pid"] == process.pid
                    and after["mode"] is mode
                    and after["connection_owned"] is mode
                )
                row["after"] = after
                status, body = api["request"](port, "/runtime")
                assert status == 200 and json.loads(body) == runtime
                assert api["fingerprints"](config) == fp
                rows.append(row)
                (directory / "record.json").write_text(json.dumps(row, indent=2))
                print(
                    "WINDOW",
                    index,
                    "mode",
                    mode,
                    "pid",
                    process.pid,
                    "good",
                    metrics["good"],
                    flush=True,
                )
    finally:
        for index, row in enumerate(rows):
            row["cleanup_pass"] = state.get("cleanup_pass", False)
            (root / f"trial-{index}" / "record.json").write_text(json.dumps(row, indent=2))
        (root / "server-state.json").write_text(json.dumps(state, indent=2))
    if args.control_only:
        assert not rows and state["cleanup_pass"]
        summary = {
            "qualified": False,
            "control_only": True,
            "native_windows": 0,
            "cleanup_pass": True,
            "runtime": state["runtime"],
        }
        (root / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return
    assert len(rows) == 4 and state["cleanup_pass"]
    compare = runpy.run_path(str(harness / "evaluate.py"))["compare"]
    summary = {
        "qualified": False,
        "same_pid": rows[0]["runtime"]["pid"],
        "off_aa_forward": compare(plan, [rows[0]], [rows[3]]),
        "off_aa_reverse": compare(plan, [rows[3]], [rows[0]]),
        "on_aa_forward": compare(plan, [rows[1]], [rows[2]]),
        "on_aa_reverse": compare(plan, [rows[2]], [rows[1]]),
        "on_off_first": compare(plan, [rows[0]], [rows[1]]),
        "on_off_reverse_order": compare(plan, [rows[3]], [rows[2]]),
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    checks = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    (root / "checksums.json").write_text(json.dumps(checks, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control-only",
        action="store_true",
        help="Exercise actual backend transitions and cleanup without native timing",
    )
    parser.add_argument("--profile", choices=["flat", "mixed"], default="mixed")
    for name in ["python", "wheel", "harness", "wrk", "collector", "output"]:
        parser.add_argument("--" + name, required=True)
    run(parser.parse_args())
