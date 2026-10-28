#!/usr/bin/env python3
"""Collect actual handler waits using the original native-client harness (not qualification)."""

import argparse
import hashlib
import json
import os
import runpy
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(trial, dump):
    pid = trial.get("runtime", {}).get("pid")
    if not dump or pid is None or dump.get("pid") != pid or trial.get("wait_pid") != pid:
        raise ValueError("wait dump/serving PID mismatch")
    if dump.get("drops") != 0 or trial.get("wait_drops") != 0:
        raise ValueError("dropped wait records")
    if trial.get("requested_waits") != [0.001]:
        raise ValueError("requested_waits must be exactly [0.001]")
    metrics = trial.get("metrics") or {}
    if any(
        metrics.get(k) != 0
        for k in ("bad", "connect_errors", "read_errors", "write_errors", "timeout_errors")
    ):
        raise ValueError("response/transport errors")
    if (
        trial.get("error") is not None
        or not trial.get("cleanup_pass")
        or trial.get("client_returncode") != 0
    ):
        raise ValueError("record/cleanup/client failure")
    records = dump.get("records")
    io_good = metrics.get("io_good")
    if (
        not isinstance(records, list)
        or not records
        or type(io_good) is not int
        or io_good <= 0
        or len(records) < io_good
    ):
        raise ValueError("missing/incomplete wait records")
    if len(records) - io_good > 16 or trial.get("wait_records") != len(records):
        raise ValueError("record count/inflight mismatch")
    if any(r.get("requested_secs") != 0.001 for r in records):
        raise ValueError("wrong requested wait")
    if any(
        type(r.get(k)) is not int or r[k] < 0
        for r in records
        for k in ("elapsed_ns", "thread_cpu_ns")
    ):
        raise ValueError("invalid wait sample")
    for key in ("application", "validator", "wheel"):
        value = trial.get("fingerprints", {}).get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("missing/invalid source or wheel fingerprint")
    result = {
        "pid": pid,
        "records": len(records),
        "io_good": io_good,
        "inflight_difference": len(records) - io_good,
    }
    for field in ("elapsed_ns", "thread_cpu_ns"):
        ordered = sorted(r[field] for r in records)
        result[field] = {
            "p50": int(statistics.median(ordered)),
            "p95": ordered[int(0.95 * (len(ordered) - 1))],
            "p99": ordered[int(0.99 * (len(ordered) - 1))],
            "max": ordered[-1],
        }
    return result


def audit(directory):
    result = {}
    for role in ("original", "current"):
        root = Path(directory) / role
        trial = json.loads((root / "trial.json").read_text())
        result[role] = validate(trial, json.loads((root / "io-waits.json").read_text()))
        manifest = Path(directory) / "inputs.json"
        if manifest.exists():
            expected = json.loads(manifest.read_text())[role]
            if trial["fingerprints"]["wheel"] != expected["wheel_sha256"]:
                raise ValueError("wheel fingerprint does not match frozen input")
    return result


def collect(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    original_harness = Path(args.harness).resolve()
    source = original_harness.parent if original_harness.is_file() else original_harness
    harness = output / "harness"
    shutil.copytree(source, harness)
    api = runpy.run_path(str(harness / "run.py"))
    plan = json.loads((harness / "plan.json").read_text())
    assert plan["client_threads"] == 4 and plan["connections"] == 16 and plan["pool"] == 16
    cell = next(c for c in plan["matrix"] if c["id"] == "gil-mixed-1")
    plan.update(duration_s=15, matrix=[cell])
    plan_path = output / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    inputs = {}
    for role in ("original", "current"):
        # Keep the venv executable path: resolving its symlink selects the bare interpreter.
        python = str(Path(getattr(args, role + "_python")).absolute())
        wheel = Path(getattr(args, role + "_wheel")).resolve()
        inputs[role] = {"python": python, "wheel": str(wheel), "wheel_sha256": sha(wheel)}
    (output / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    for role, item in inputs.items():
        directory = output / role
        directory.mkdir()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHON_GIL", "IO_WAIT_DIAGNOSTIC_PATH")
            and not k.startswith("DEXPOT_")
        }
        env.update(
            DEXPOT_WORKERS="1",
            DEXPOT_HTTP_PARSER="python",
            DEXPOT_POOL="16",
            DEXPOT_MAX_QUEUE="16",
            DEXPOT_MAX_CONNECTIONS="32",
            PYTHONUNBUFFERED="1",
            PYTHONPATH=str(Path(args.collector).resolve()),
            IO_WAIT_DIAGNOSTIC_PATH=str(directory / "io-waits.json"),
        )
        identity = json.loads(
            subprocess.check_output(
                [item["python"], "-c", api["PROBE"], item["wheel"]], env=env, text=True
            )
        )
        if not identity["gil_enabled"] or identity["ft_build"]:
            raise ValueError("requires unforced GIL runtime")
        config = SimpleNamespace(
            plan=plan_path,
            wheel=Path(item["wheel"]),
            wrk=Path(args.wrk).resolve(),
            identities={"gil": identity},
        )
        fingerprints = api["fingerprints"](config)
        trial = api["trial"](cell, plan, item["python"], env, directory, config, fingerprints)
        # Persist the original record even if collector validation later fails.
        (directory / "raw-trial.json").write_text(json.dumps(trial, indent=2) + "\n")
        dump = json.loads((directory / "io-waits.json").read_text())
        trial.update(
            wait_pid=dump["pid"],
            wait_drops=dump["drops"],
            wait_records=len(dump["records"]),
            requested_waits=sorted({r["requested_secs"] for r in dump["records"]}),
        )
        (directory / "trial.json").write_text(json.dumps(trial, indent=2) + "\n")
        if trial["runtime"]["module"] != identity["module"]:
            raise ValueError("serving module differs from verified installed artifact")
        for name in ("application", "validator"):
            file = "application.py" if name == "application" else "validate.lua"
            if fingerprints[name] != sha(source / file):
                raise ValueError("original workload/validator changed")
        if fingerprints["wheel"] != item["wheel_sha256"]:
            raise ValueError("wheel changed after input freeze")
        resources = trial.get("resources", {})
        if not resources.get("complete") or any(
            resources.get(k, float("inf")) > limit for k, limit in plan["budgets"].items()
        ):
            raise ValueError("resource recording incomplete or over unchanged budget")
        validate(trial, dump)
    result = audit(output)
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", metavar="DIRECTORY")
    for key in (
        "harness",
        "collector",
        "original-python",
        "original-wheel",
        "current-python",
        "current-wheel",
        "wrk",
        "output",
    ):
        parser.add_argument("--" + key)
    args = parser.parse_args()
    if args.audit_only:
        print(json.dumps(audit(args.audit_only), indent=2))
        return
    if any(
        not getattr(args, key)
        for key in (
            "harness",
            "collector",
            "original_python",
            "original_wheel",
            "current_python",
            "current_wheel",
            "wrk",
            "output",
        )
    ):
        parser.error(
            "measurement requires all artifact, harness, collector, client and output arguments"
        )
    print(json.dumps(collect(args), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2) from error
