"""Bounded installed-wheel baseline. Native wrk-adjusted latency is not an SLO."""

import argparse
import contextlib
import hashlib
import http.client
import json
import math
import os
import platform
import runpy
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psutil

ROOT = Path(__file__).resolve().parent
PREFLIGHT_LIMITS = {"DEXPOT_POOL": "2", "DEXPOT_MAX_QUEUE": "2", "DEXPOT_MAX_CONNECTIONS": "4"}
FLAT = b'{"id":7,"name":"item-7","price":9.99}'
PROBE = """
import hashlib,importlib.metadata,json,sys,sysconfig,zipfile
from pathlib import Path
import dexpot,msgspec
root=Path(dexpot.__file__).parent
assert 'site-packages' in root.parts, 'editable/source imports are not eligible'
z=zipfile.ZipFile(sys.argv[1]); h=hashlib.sha256()
for name in sorted(n for n in z.namelist() if n.startswith('dexpot/') and n.endswith('.py')):
 data=z.read(name);assert (root.parent/name).read_bytes()==data,name
 h.update(name.encode());h.update(data)
print(json.dumps(dict(module=dexpot.__file__,version=importlib.metadata.version('dexpot'),
 python=sys.version,msgspec=msgspec.__version__,gil_enabled=sys._is_gil_enabled(),
 ft_build=bool(sysconfig.get_config_var('Py_GIL_DISABLED')),source_sha256=h.hexdigest())))
"""


def parse_metrics(output: str, profile: str) -> dict:
    lines = [
        line.removeprefix("METRICS ") for line in output.splitlines() if line.startswith("METRICS ")
    ]
    if len(lines) != 1:
        raise ValueError("expected exactly one METRICS record")
    metrics = json.loads(lines[0])
    keys = (
        "requests",
        "good",
        "bad",
        "duration_us",
        "p50_us",
        "p95_us",
        "p99_us",
        "connect_errors",
        "read_errors",
        "write_errors",
        "timeout_errors",
        "flat_good",
        "nested_good",
        "cpu_good",
        "io_good",
    )
    if not all(
        type(metrics.get(key)) in (int, float) and math.isfinite(metrics[key]) and metrics[key] >= 0
        for key in keys
    ):
        raise ValueError("missing or invalid metric")
    routes = ("flat", "nested", "cpu", "io") if profile == "mixed" else (profile,)
    if any(metrics.get(route + "_good", 0) <= 0 for route in routes):
        raise ValueError("a required route cohort did not validate traffic")
    return metrics


def verify_runtime(observed: dict, expected: dict, mode: str) -> None:
    keys = ("module", "version", "gil_enabled", "ft_build")
    if any(observed.get(key) != expected.get(key) for key in keys):
        raise ValueError("serving worker differs from verified installed artifact")
    if observed.get("parser") != "python" or observed.get("selected_ft") is not (mode == "ft"):
        raise ValueError("unexpected serving parser or scheduler")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def request(port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@contextlib.contextmanager
def server(python: str, env: dict, log: Path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state: dict[str, Any] = {"cleanup_pass": False}
    with log.open("x") as output:
        process = subprocess.Popen(
            [python, str(ROOT / "application.py"), "--port", str(port)],
            env=env,
            cwd=log.parent,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("server exited: " + log.read_text())
                try:
                    status, body = request(port, "/runtime")
                    if status != 200:
                        raise RuntimeError("runtime preflight did not succeed")
                    state["runtime"] = json.loads(body)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("listener startup") from None
                    time.sleep(0.02)
            yield process, port, state
        finally:
            forced = False
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                forced = True
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

            def group_alive():
                try:
                    os.killpg(process.pid, 0)
                    return True
                except ProcessLookupError:
                    return False

            if group_alive():
                forced = True
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                deadline = time.monotonic() + 3
                while group_alive() and time.monotonic() < deadline:
                    time.sleep(0.02)
            state["group_exited"] = not group_alive()
            with socket.socket() as sock:
                state["cleanup_pass"] = (
                    not forced
                    and state["group_exited"]
                    and process.returncode == 0
                    and sock.connect_ex(("127.0.0.1", port)) != 0
                )


def _wait_preflight_state(
    connection, mode: str, *, full: bool = False, occupied: int | None = None
) -> dict:
    positions = occupied if occupied is not None else (4 if full else 1)
    deadline = time.monotonic() + 2
    while True:
        connection.request("GET", "/_preflight")
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError("preflight admission observer did not succeed")
        observed = json.loads(body)
        if mode == "ft":
            desired = {"active": positions, "queued": 0, "live_ft_owners": positions}
        else:
            desired = {"active": min(2, positions), "queued": max(0, positions - 2)}
        if all(observed.get(key) == value for key, value in desired.items()):
            return observed
        if time.monotonic() >= deadline:
            raise TimeoutError("preflight admission state did not settle: " + repr(observed))
        time.sleep(0.01)


def preflight(python: str, env: dict, log: Path, expected: dict, mode: str, frozen: dict) -> dict:
    result: dict[str, Any] = {"churn_pass": False, "overload_pass": False, "cleanup_pass": False}
    limited = dict(env, **PREFLIGHT_LIMITS, DEXPOT_PREFLIGHT_BARRIER="1")
    result.update(fingerprints=frozen, limits=dict(PREFLIGHT_LIMITS))
    state: dict[str, Any] = {}
    try:
        with server(python, limited, log) as (_, port, state):
            verify_runtime(state["runtime"], expected, mode)
            result["runtime"] = state["runtime"]
            result["churn_pass"] = all(request(port, "/flat") == (200, FLAT) for _ in range(8))
            # Keep the observer connection as the first held position. Closed
            # churn peers must release admission before the other three open.
            barrier = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            held = []
            try:
                result["quiescent_state"] = _wait_preflight_state(barrier, mode, full=False)
                result["admitted_states"] = []
                for positions in range(2, 5):
                    held.append(socket.create_connection(("127.0.0.1", port), timeout=2))
                    # Let an idle GIL worker claim the first peer before its
                    # bounded queue can reject a burst of later held peers.
                    result["admitted_states"].append(
                        _wait_preflight_state(barrier, mode, occupied=positions)
                    )
                result["saturated_state"] = result["admitted_states"][-1]
                result["overload_pass"] = request(port, "/flat")[0] == 503
            finally:
                for connection in held:
                    connection.close()
                barrier.close()
        result["cleanup_pass"] = state["cleanup_pass"]
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        result["cleanup_pass"] = state.get("cleanup_pass", False)
    return result


def snapshot(process: "psutil.Process") -> dict:
    with process.oneshot():
        cpu = process.cpu_times()
        return {
            "t": time.monotonic(),
            "cpu": cpu.user + cpu.system,
            "rss": process.memory_info().rss,
            "threads": process.num_threads(),
            "fds": process.num_fds(),
            "children": len(process.children()),
        }


def resources(samples: list) -> dict:
    if len(samples) < 3:
        return {"complete": False}
    elapsed = samples[-1]["t"] - samples[0]["t"]
    return {
        "complete": elapsed > 0 and all(s["children"] == 0 for s in samples),
        "cpu_cores": (samples[-1]["cpu"] - samples[0]["cpu"]) / elapsed,
        "rss_bytes": max(s["rss"] for s in samples),
        "threads": max(s["threads"] for s in samples),
        "fds": max(s["fds"] for s in samples),
        "samples": len(samples),
        "sampled_interval_s": elapsed,
        "scope": "sampled single serving process; 100ms interval",
    }


def fingerprints(args) -> dict:
    return {
        "application": sha(ROOT / "application.py"),
        "validator": sha(ROOT / "validate.lua"),
        "runner": sha(Path(__file__)),
        "evaluator": sha(ROOT / "evaluate.py"),
        "plan": sha(args.plan),
        "client": sha(args.wrk),
        "wheel": sha(args.wheel),
    }


def trial(cell: dict, plan: dict, python: str, env: dict, out: Path, args, frozen: dict) -> dict:
    import psutil

    row = {
        "cell": cell,
        "fingerprints": frozen,
        "metrics": None,
        "resources": {"complete": False},
        "error": None,
        "cleanup_pass": False,
        "client_returncode": None,
    }
    save(out / (cell["id"] + ".started.json"), {"cell": cell, "started_epoch": time.time()})
    state = {}
    try:
        if fingerprints(args) != frozen:
            raise RuntimeError("frozen measurement inputs changed")
        with server(python, env, out / (cell["id"] + ".server.log")) as (process, port, state):
            row["runtime"] = state["runtime"]
            verify_runtime(row["runtime"], args.identities[cell["runtime"]], cell["runtime"])
            if row["runtime"]["gil_enabled"] is not (cell["runtime"] == "gil"):
                raise RuntimeError("actual worker GIL state mismatch")
            for route in ("flat", "cpu", "io"):
                if request(port, "/" + route) != (200, FLAT):
                    raise RuntimeError("workload preflight mismatch")
            command = [
                str(args.wrk),
                "-t",
                str(plan["client_threads"]),
                "-c",
                str(plan["connections"]),
                "-d",
                str(plan["duration_s"]) + "s",
                "--latency",
                "-s",
                str(ROOT / "validate.lua"),
                f"http://127.0.0.1:{port}",
                "--",
                cell["profile"],
            ]
            row["command"] = command
            monitor = psutil.Process(process.pid)
            samples = [snapshot(monitor)]
            client_samples = []
            client = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
            )
            deadline = time.monotonic() + plan["duration_s"] + 15
            try:
                client_monitor = psutil.Process(client.pid)
                while client.poll() is None and time.monotonic() < deadline:
                    samples.append(snapshot(monitor))
                    with contextlib.suppress(psutil.NoSuchProcess):
                        client_samples.append(snapshot(client_monitor))
                    time.sleep(0.1)
                if client.poll() is None:
                    client.kill()
                    row["error"] = "native client exceeded deadline"
                stdout, stderr = client.communicate(timeout=3)
            finally:
                if client.poll() is None:
                    client.kill()
                    client.communicate(timeout=3)
            row.update(
                client_returncode=client.returncode,
                stdout=stdout,
                stderr=stderr,
                resources=resources(samples),
                client_resources=resources(client_samples),
            )
            row["metrics"] = parse_metrics(stdout, cell["profile"])
            status, body = request(port, "/runtime")
            if status != 200 or json.loads(body) != row["runtime"]:
                raise RuntimeError("worker runtime identity changed after load")
    except Exception as exc:
        row["error"] = repr(exc)
    finally:
        row["cleanup_pass"] = state.get("cleanup_pass", False)
        if fingerprints(args) != frozen:
            row["error"] = "measurement inputs changed during trial"
        save(out / (cell["id"] + ".json"), row)
    return row


def validate_plan(plan: dict) -> None:
    # Owners retain keep-alive until close; queued cohorts cannot receive a turn.
    if type(plan.get("pool")) is not int or plan["pool"] < plan["connections"]:
        raise ValueError("the GIL pool must admit every persistent connection in this screen")


def record(args) -> int:
    import psutil

    if os.name != "posix" or os.environ.get("PYTHON_GIL") or "gil" in sys._xoptions:
        raise ValueError("requires POSIX process/fd monitoring and unforced interpreter modes")
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    if (
        not 1 <= plan["duration_s"] <= 60
        or plan["client_threads"] != 4
        or plan["connections"] != 16
    ):
        raise ValueError("screen requires 1..60s, four client threads and sixteen connections")
    ids = [cell["id"] for cell in plan["matrix"]]
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(not value.replace("-", "").isalnum() for value in ids)
    ):
        raise ValueError("empty, duplicate or unsafe trial identifiers")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEXPOT_") and k != "PYTHONPATH"}
    env.update(
        DEXPOT_WORKERS="1",
        DEXPOT_HTTP_PARSER="python",
        DEXPOT_POOL=str(plan["pool"]),
        DEXPOT_MAX_QUEUE="16",
        DEXPOT_MAX_CONNECTIONS="32",
        PYTHONUNBUFFERED="1",
    )
    runtimes = {cell["runtime"] for cell in plan["matrix"]}
    interpreters = {mode: getattr(args, "python_" + mode) for mode in runtimes}
    if any(not python for python in interpreters.values()):
        raise ValueError("every planned runtime needs an explicit interpreter")
    args.output.mkdir(parents=True, exist_ok=args.resume)
    import fcntl

    with (args.output / ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = fingerprints(args)
        identities = {}
        for mode, python in interpreters.items():
            identities[mode] = json.loads(
                subprocess.check_output(
                    [python, "-c", PROBE, str(args.wheel)], env=env, text=True, timeout=15
                )
            )
            if identities[mode]["gil_enabled"] is not (mode == "gil") or identities[mode][
                "ft_build"
            ] is not (mode == "ft"):
                raise ValueError("installed interpreter build/GIL mismatch")
        manifest = {
            "fingerprints": frozen,
            "plan": plan,
            "runtime": identities,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "psutil": psutil.__version__,
            "controller_python": sys.version,
        }
        target = args.output / "manifest.json"
        if target.exists():
            if json.loads(target.read_text()) != manifest:
                raise ValueError("resume cannot change frozen measurement inputs")
        else:
            save(target, manifest)
        args.identities = identities
        preflights = {}
        for mode, python in interpreters.items():
            path = args.output / (mode + ".preflight.json")
            if path.exists():
                preflights[mode] = json.loads(path.read_text())
            else:
                preflights[mode] = preflight(
                    python,
                    env,
                    args.output / (mode + ".preflight.log"),
                    identities[mode],
                    mode,
                    frozen,
                )
                save(path, preflights[mode])
        rows = []
        for cell in plan["matrix"]:
            path = args.output / (cell["id"] + ".json")
            if path.exists():
                rows.append(json.loads(path.read_text()))
            elif not (args.output / (cell["id"] + ".started.json")).exists():
                rows.append(
                    trial(cell, plan, interpreters[cell["runtime"]], env, args.output, args, frozen)
                )
                print(cell["id"], "saved", flush=True)
        report = check_recording(manifest, rows, preflights)
        # Reports are derived; preserve every report generation as well as raw trials.
        save(
            args.output
            / ("report.json" if not args.resume else f"report-resume-{time.time_ns()}.json"),
            report,
        )
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report["status"] == "baseline-recorded" else 1


def check_recording(manifest: dict, rows: list, controls: dict) -> dict:
    evaluate = runpy.run_path(str(ROOT / "evaluate.py"))["evaluate"]
    report = evaluate(manifest["plan"], rows, controls)
    if report["status"] != "baseline-recorded":
        return report
    try:
        modes = {cell["runtime"] for cell in manifest["plan"]["matrix"]}
        if set(controls) != modes or set(manifest["runtime"]) != modes:
            raise ValueError("recording has inconsistent runtime/control inventory")
        for row in rows:
            mode = row["cell"]["runtime"]
            if row.get("fingerprints") != manifest["fingerprints"]:
                raise ValueError("trial is detached from its artifact/input manifest")
            verify_runtime(row["runtime"], manifest["runtime"][mode], mode)
        for mode, control in controls.items():
            if (
                control.get("fingerprints") != manifest["fingerprints"]
                or control.get("limits") != PREFLIGHT_LIMITS
            ):
                raise ValueError("preflight provenance or limits changed")
            verify_runtime(control["runtime"], manifest["runtime"][mode], mode)
    except (ValueError, KeyError, TypeError) as exc:
        report["status"] = "invalid"
        report["errors"].append(str(exc))
    return report


def compare_directories(args) -> int:
    result = {"status": "invalid", "errors": [], "pairs": []}
    try:
        base = json.loads((args.baseline / "manifest.json").read_text())
        cand = json.loads((args.candidate / "manifest.json").read_text())
        for key in ("plan", "platform", "machine", "cpu_count", "psutil", "controller_python"):
            if base[key] != cand[key]:
                raise ValueError("incompatible comparison environment: " + key)
        for key, value in base["fingerprints"].items():
            if key != "wheel" and cand["fingerprints"].get(key) != value:
                raise ValueError("measurement contract changed: " + key)
        if base["fingerprints"]["wheel"] == cand["fingerprints"]["wheel"]:
            raise ValueError("identical artifacts cannot establish a candidate change")
        for mode, identity in base["runtime"].items():
            other = cand["runtime"][mode]
            for key in ("python", "msgspec", "gil_enabled", "ft_build"):
                if identity[key] != other[key]:
                    raise ValueError("interpreter/dependency mismatch: " + key)
            if identity["source_sha256"] == other["source_sha256"]:
                raise ValueError("identical installed sources cannot establish a candidate change")
        api = runpy.run_path(str(ROOT / "evaluate.py"))
        observations = []
        for folder, manifest in ((args.baseline, base), (args.candidate, cand)):
            rows = []
            for path in folder.glob("*.json"):
                if (
                    path.name == "manifest.json"
                    or path.name.startswith("report")
                    or path.name.endswith((".started.json", ".preflight.json"))
                ):
                    continue
                rows.append(json.loads(path.read_text()))
            controls = {
                mode: json.loads((folder / (mode + ".preflight.json")).read_text())
                for mode in manifest["runtime"]
                if mode in ("gil", "ft")
            }
            validation = check_recording(manifest, rows, controls)
            if validation["status"] != "baseline-recorded":
                raise ValueError("incomplete or invalid recording: " + str(validation["errors"]))
            observations.append(rows)
        result = api["compare"](base["plan"], *observations)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result["errors"] = [str(exc)]
    save(args.output, result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "screen-passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sub = commands.add_parser("record", help="record a baseline, not a candidate acceptance")
    sub.add_argument("--plan", type=Path, default=ROOT / "plan.json")
    sub.add_argument("--python-gil")
    sub.add_argument("--python-ft")
    sub.add_argument("--wheel", type=Path, required=True)
    sub.add_argument("--wrk", type=Path, required=True)
    sub.add_argument("--output", type=Path, required=True)
    sub.add_argument("--resume", action="store_true")
    other = commands.add_parser(
        "compare", help="fail-closed paired candidate screen, not release qualification"
    )
    other.add_argument("--baseline", type=Path, required=True)
    other.add_argument("--candidate", type=Path, required=True)
    other.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return record(args) if args.command == "record" else compare_directories(args)


if __name__ == "__main__":
    raise SystemExit(main())
