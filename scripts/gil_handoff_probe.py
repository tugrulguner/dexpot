"""One-variable GIL handoff diagnostic, same PID, stock/short/short/stock. Not qualification."""

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

from port_capture import capture_port

WHEEL = "d49d77422bc34ce94b40d603a4f9c3b49030310bbbc3308b84ea8f4bf5a29cc2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wrk", type=Path, required=True)
    parser.add_argument("--capture-loopback", action="store_true")
    args = parser.parse_args()
    root = args.root
    root.mkdir(exist_ok=False)
    if not args.capture_loopback:
        raise ValueError("this diagnostic requires identical capture in all windows")
    intervals = [0.005, 0.0005, 0.0005, 0.005]
    modes = ["stock-before", "short-first", "short-second", "stock-after"]
    original = Path(__file__).parent / "lifecycle_preflight_harness"
    harness = root / "harness"
    shutil.copytree(original, harness)
    helper = Path(__file__).parent / "request_marker_sidecar.py"
    shutil.copy2(helper, harness / helper.name)
    client_appendix = (Path(__file__).parent / "request_marker_client.lua").read_bytes()
    application = harness / "application.py"
    before = application.read_text()
    after = (
        before.replace(
            "import sys\n", "import sys\nfrom request_marker_sidecar import install, flush\n", 1
        )
        .replace("app = Dex()\n", "app = Dex()\ninstall(app)\n", 1)
        .replace("def runtime() -> dict:\n", "def runtime() -> dict:\n    flush()\n", 1)
    )

    interval_helper = Path(__file__).parent / "gil_interval_control.py"
    shutil.copy2(interval_helper, harness / interval_helper.name)
    after = after.replace(
        "from request_marker_sidecar import install, flush\n",
        "from request_marker_sidecar import install, flush\nfrom gil_interval_control import apply_requested\n",
        1,
    ).replace("def runtime() -> dict:\n", "def runtime() -> dict:\n    apply_requested()\n", 1)

    def handlers(text):
        return {
            n.name: ast.dump(n)
            for n in ast.parse(text).body
            if isinstance(n, ast.FunctionDef) and n.name in ("flat", "nested", "cpu", "io")
        }

    assert handlers(before) == handlers(after)
    application.write_text(after)
    validator = harness / "validate.lua"
    validator_bytes = validator.read_bytes()
    plan = json.loads((original / "plan.json").read_text())
    plan["duration_s"] = 15
    cell = next(c for c in plan["matrix"] if c["id"] == "gil-flat-1")
    plan["matrix"] = [cell]
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    assert sha(args.wheel) == WHEEL
    shutil.copy2(args.wheel, root / args.wheel.name)
    logs = root / "markers"
    logs.mkdir()
    protocol = {
        "windows": modes,
        "gil_interval_order_s": intervals,
        "interval_helper_sha256": sha(interval_helper),
        "hypotheses_ranked": [
            "GIL handoff interval sensitivity",
            "OS/VM scheduling independent of interval",
            "observer perturbation",
        ],
        "prediction": "Short interval must reduce server tap-to-parsed waiting in both temporal orders; inconsistent directions are inconclusive/reject promotion. No global-cause proof or production tuning inferred.",
        "duration_s": 15,
        "sample_every": 64,
        "capture_loopback": args.capture_loopback,
        "capture_scope": "only owned synthetic localhost server port; disposable CI; packet tap observations, not syscall timestamps",
        "analysis_slow_threshold_us": 10000,
        "analysis_dominant_fraction": 0.8,
        "analysis_cross_clock_tolerance_us": 2,
        "analysis_wall_mono_disagreement_limit_us": 100,
        "server_lifecycles": 1,
        "seed": "1",
        "wheel_sha256": WHEEL,
        "validator_original_sha256": hashlib.sha256(validator_bytes).hexdigest(),
        "appendix_sha256": hashlib.sha256(client_appendix).hexdigest(),
        "server_sidecar_sha256": sha(helper),
        "handler_asts_identical": True,
        "native_client_sha256": sha(args.wrk),
        "scope": "same-PID process-local GIL interval intervention; no runtime PR or host-policy changes; not qualification; no retries",
        "limits": "All four windows use identical marked clients and port-scoped packet capture. Only the owned server interval changes between windows through an untimed runtime probe. Results are interval sensitivity, not proof of a unique historical cause or justification to tune library users globally.",
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
        DIAG_DIR=str(logs),
        DIAG_ENABLED="1",
    )
    control = root / "interval-control.json"
    control.write_text(json.dumps({"sequence": -1, "interval_s": 0.005}))
    attest_dir = root / "interval-attestations"
    attest_dir.mkdir()
    env.update(DIAG_INTERVAL_CONTROL=str(control), DIAG_INTERVAL_ATTEST=str(attest_dir))
    identity = json.loads(
        subprocess.check_output(
            [args.python, "-c", api["PROBE"], str(args.wheel)], env=env, text=True
        )
    )
    assert identity["gil_enabled"] is True and identity["ft_build"] is False
    config = SimpleNamespace(
        plan=plan_path, wheel=args.wheel, wrk=args.wrk, identities={"gil": identity}
    )
    original_frozen = api["fingerprints"](config)
    preflight = api["preflight"](
        args.python, env, root / "preflight.log", identity, "gil", original_frozen
    )
    (root / "preflight.json").write_text(json.dumps(preflight, indent=2))
    assert all(preflight[k] is True for k in ("churn_pass", "overload_pass", "cleanup_pass"))
    windows = []
    state = {}
    try:
        with api["server"](args.python, env, root / "server.log") as (server, port, state):
            if args.capture_loopback:
                import time

                with capture_port(port, root / "capture-functional"):
                    assert api["request"](port, "/flat") == (200, api["FLAT"])
                    time.sleep(0.05)

            @contextlib.contextmanager
            def persistent(python, env, log):
                assert server.poll() is None
                status, body = api["request"](port, "/runtime")
                assert status == 200 and json.loads(body) == state["runtime"]
                yield server, port, state

            api["trial"].__globals__["server"] = persistent
            for index in range(4):
                assert sha(harness / helper.name) == protocol["server_sidecar_sha256"]
                validator.write_bytes(validator_bytes + b"\n" + client_appendix)
                assert validator.read_bytes().startswith(validator_bytes)
                frozen = api["fingerprints"](config)
                if index == 0:
                    timed_contract = frozen
                else:
                    assert frozen == timed_contract, (
                        "timed inputs changed beyond process-local interval"
                    )
                out = root / ("window-" + str(index))
                out.mkdir()
                assert sha(harness / interval_helper.name) == protocol["interval_helper_sha256"]
                control.write_text(json.dumps({"sequence": index, "interval_s": intervals[index]}))
                (out / "markers").mkdir()
                case_env = env.copy()
                case_env["DIAG_DIR"] = str(out / "markers")
                attest_path = attest_dir / (str(server.pid) + ".jsonl")
                start_attest = len(attest_path.read_text().splitlines())
                (out / "inputs.json").write_text(
                    json.dumps(
                        {
                            "runtime": identity,
                            "fingerprints": frozen,
                            "validator_mode": protocol["windows"][index],
                        },
                        indent=2,
                    )
                )
                capture = (
                    capture_port(port, out / "capture")
                    if args.capture_loopback
                    else contextlib.nullcontext()
                )
                with capture:
                    row = api["trial"](cell, plan, args.python, case_env, out, config, frozen)
                observed = [
                    json.loads(line) for line in attest_path.read_text().splitlines()[start_attest:]
                ]
                assert len(observed) >= 2 and all(
                    x["pid"] == server.pid
                    and x["sequence"] == index
                    and x["actual_s"] == intervals[index]
                    and x["gil_enabled"]
                    for x in observed
                )
                assert row["runtime"]["pid"] == server.pid and row["cleanup_pass"] is False
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
                            for k in (
                                "bad",
                                "connect_errors",
                                "read_errors",
                                "write_errors",
                                "timeout_errors",
                            )
                        )
                    )
                valid = (
                    valid
                    and row["resources"].get("complete") is True
                    and all(
                        row["resources"][k] <= plan["budgets"][k]
                        for k in ("rss_bytes", "threads", "fds", "cpu_cores")
                    )
                )
                windows.append(
                    {
                        "index": index,
                        "mode": protocol["windows"][index],
                        "pid": server.pid,
                        "checks_pass": valid,
                        "interval_observed": observed,
                        "raw": row,
                    }
                )
                (root / "windows.json").write_text(json.dumps(windows, indent=2))
                print("WINDOW", index, valid, metrics, flush=True)
            control.write_text(json.dumps({"sequence": 4, "interval_s": 0.005}))
            assert api["request"](port, "/runtime")[0] == 200
    finally:
        (root / "cleanup.json").write_text(
            json.dumps(
                {
                    "server_cleanup_pass": state.get("cleanup_pass", False),
                    "per_window_cleanup_not_claimed": True,
                },
                indent=2,
            )
        )
    assert state["cleanup_pass"] is True
    (root / "summary.json").write_text(
        json.dumps(
            {
                "windows": windows,
                "server_pid": server.pid,
                "server_cleanup_pass": True,
                "qualified": False,
                "status": "collected-needs-matched-marker-analysis",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
