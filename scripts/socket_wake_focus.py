"""Frozen uninstrumented Darwin mixed-1 screen, not full qualification."""

import argparse
import importlib.util
import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[1]
HEAD = "95ea8ab26e35a5404f0f5db53c6b1270d218fea3"
BASE = "ca4979a6339e533f11ad135bc760aa081f3f60ab"


def prepare():
    spec = importlib.util.spec_from_file_location(
        "socket_diag", REPO / "scripts/socket_owner_diagnostic.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CANDIDATE = HEAD
    driver = module.DRIVER
    driver.HEAD = HEAD
    driver.RUN_REQUEST = module.request_spec()
    driver.PREPARE_ONLY = True
    return driver.execute_qualification()


def measure():
    prepared = Path(os.environ["RUNNER_TEMP"]) / "dexpot-socket-runtime-qualification"
    proof = json.loads((prepared / "evidence/preparation-only.json").read_text())
    assert proof["head_sha"] == HEAD and proof["qualified"] is False
    root = prepared / "evidence/wake-focus"
    root.mkdir(exist_ok=False)
    harness = root / "harness"
    shutil.copytree(REPO / "scripts/lifecycle_preflight_harness", harness)
    api = runpy.run_path(str(harness / "run.py"))
    plan = json.loads((harness / "plan.json").read_text())
    cell = next(c for c in plan["matrix"] if c["id"] == "gil-mixed-1")
    plan.update(duration_s=15, matrix=[cell])
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    protocol = {
        "source_base": BASE,
        "source_head": HEAD,
        "order": ["stock", "repair", "repair", "stock"],
        "duration_s": 15,
        "client_threads": plan["client_threads"],
        "connections": plan["connections"],
        "budgets": plan["budgets"],
        "comparison": plan["comparison"],
        "no_retries": True,
        "qualified": False,
        "scope": "Focused original-client mixed-1 screen of changed Darwin wake strategy; cannot clear full-matrix losses.",
    }
    (root / "predeclared.json").write_text(json.dumps(protocol, indent=2) + "\n")
    artifacts = {
        role: (
            str(prepared / (prefix + "-gil/bin/python")),
            prepared / ("dist-" + prefix) / "dexpot-0.7.1-py3-none-any.whl",
        )
        for role, prefix in [("stock", "main"), ("repair", "pr")]
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHON_GIL", "PYTHONPATH", "IO_WAIT_DIAGNOSTIC_PATH")
        and not k.startswith("DEXPOT_")
    }
    env.update(
        DEXPOT_WORKERS="1",
        DEXPOT_HTTP_PARSER="python",
        DEXPOT_POOL="16",
        DEXPOT_MAX_QUEUE="16",
        DEXPOT_MAX_CONNECTIONS="32",
        PYTHONUNBUFFERED="1",
    )
    configs = {}
    preflights = {}
    wrk = shutil.which("wrk")
    if wrk is None:
        raise FileNotFoundError("original native client wrk is required")
    for role, (python, wheel) in artifacts.items():
        directory = root / role
        directory.mkdir()
        identity = json.loads(
            subprocess.check_output([python, "-c", api["PROBE"], str(wheel)], env=env, text=True)
        )
        assert identity["gil_enabled"] and not identity["ft_build"]
        config = SimpleNamespace(
            plan=plan_path, wheel=wheel, wrk=Path(wrk), identities={"gil": identity}
        )
        fingerprints = api["fingerprints"](config)
        configs[role] = config, fingerprints, identity
        preflight = api["preflight"](
            python, env, directory / "preflight.log", identity, "gil", fingerprints
        )
        (directory / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n")
        assert all(preflight[k] for k in ["churn_pass", "overload_pass", "cleanup_pass"])
        preflights[role] = preflight
    rows = []
    for index, role in enumerate(protocol["order"]):
        directory = root / f"trial-{index}-{role}"
        directory.mkdir()
        config, fingerprints, identity = configs[role]
        row = api["trial"](cell, plan, artifacts[role][0], env, directory, config, fingerprints)
        report = api["check_recording"](
            {"plan": plan, "fingerprints": fingerprints, "runtime": {"gil": identity}},
            [row],
            {"gil": preflights[role]},
        )
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        rows.append(row)
        print(index, role, report["status"], row.get("metrics"), flush=True)
    compare = runpy.run_path(str(harness / "evaluate.py"))["compare"]
    summary = {
        "qualified": False,
        "source_head": HEAD,
        "aa_forward": compare(plan, [rows[0]], [rows[3]]),
        "aa_reverse": compare(plan, [rows[3]], [rows[0]]),
        "repair_stock_forward": compare(plan, [rows[0]], [rows[1]]),
        "repair_stock_reverse_order": compare(plan, [rows[3]], [rows[2]]),
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise ValueError("no retries")
    if args.prepare_only:
        prepare()
    else:
        measure()


if __name__ == "__main__":
    main()
