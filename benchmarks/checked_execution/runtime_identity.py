"""Benchmark-only server identity capture and fail-closed lifecycle validation."""

import importlib.metadata
import json
import os
import sys
from typing import Any

PREFIX = "RUNTIME_IDENTITY "


def runtime_snapshot(app: Any, phase: str) -> dict[str, Any]:
    info = app._runtime_info()
    info.update(
        phase=phase,
        active_connections=len(app._active_connections),
        launch_overrides={
            "PYTHON_GIL": os.environ.get("PYTHON_GIL"),
            "gil": sys._xoptions.get("gil"),
        },
        dependencies={name: importlib.metadata.version(name) for name in ("dexpot", "msgspec")},
    )
    native = sys.modules.get("dexpot_native")
    if native is not None:
        info["dependencies"]["dexpot-native"] = getattr(native, "__version__", "unknown")
    return info


def emit_runtime_event(app: Any, phase: str) -> None:
    # One write keeps fork-worker records intact in a shared stdout pipe.
    payload = (PREFIX + json.dumps(runtime_snapshot(app, phase)) + "\n").encode()
    if len(payload) > 4096:
        raise RuntimeError("runtime identity record exceeds atomic pipe-write bound")
    if os.write(1, payload) != len(payload):
        raise RuntimeError("incomplete runtime identity record")


def validate_runtime_events(
    log: str, *, expected_runtime: str, expected_processes: int
) -> dict[str, Any]:
    if expected_runtime not in {"gil", "ft", "ft-gil"} or expected_processes < 1:
        raise ValueError("explicit runtime and positive serving-process count required")
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    records: dict[tuple[int, str], dict[str, Any]] = {}
    build, gil = expected_runtime != "gil", expected_runtime != "ft"
    for line in log.splitlines():
        if not line.startswith(PREFIX):
            continue
        try:
            value = json.loads(line[len(PREFIX) :])
            if not isinstance(value, dict):
                raise ValueError("identity is not an object")
        except (ValueError, TypeError) as exc:
            errors.append(f"malformed runtime identity: {exc}")
            continue
        events.append(value)
        pid, phase = value.get("pid"), value.get("phase")
        if type(pid) is not int or pid <= 0 or phase not in {"startup", "after_workload"}:
            errors.append("invalid PID or lifecycle phase")
            continue
        key = (pid, phase)
        if key in records:
            errors.append(f"duplicate runtime identity for {pid}/{phase}")
        records[key] = value
        if value.get("free_threaded_build") is not build or value.get("gil_enabled") is not gil:
            errors.append(f"build/GIL mismatch at {pid}/{phase}")
        if value.get("selected_gil_enabled") is not gil or value.get("execution_mode") != (
            "pooled-gil" if gil else "bounded-ft"
        ):
            errors.append(f"selected execution mode mismatch at {pid}/{phase}")
        if value.get("launch_overrides") != {"PYTHON_GIL": None, "gil": None}:
            errors.append(f"forced or missing launch evidence at {pid}/{phase}")
        dependencies = value.get("dependencies")
        if not isinstance(dependencies, dict) or any(
            not isinstance(dependencies.get(name), str) or not dependencies[name]
            for name in ("dexpot", "msgspec")
        ):
            errors.append(f"missing dependency versions at {pid}/{phase}")
        if not isinstance(value.get("python"), str) or not value["python"]:
            errors.append(f"missing interpreter version at {pid}/{phase}")
        if phase == "after_workload" and value.get("active_connections") != 0:
            errors.append(f"unfinished active work at {pid}/{phase}")
    startup = {pid for pid, phase in records if phase == "startup"}
    final = {pid for pid, phase in records if phase == "after_workload"}
    if startup != final or len(startup) != expected_processes:
        errors.append("missing or changed serving-process lifecycle set")
    for pid in startup & final:
        before, after = records[pid, "startup"], records[pid, "after_workload"]
        if before.get("python") != after.get("python"):
            errors.append(f"interpreter identity changed for {pid}")
        for name, version in (before.get("dependencies") or {}).items():
            if (after.get("dependencies") or {}).get(name) != version:
                errors.append(f"dependency identity changed for {pid}/{name}")
    return {
        "valid": not errors,
        "errors": errors,
        "pids": sorted(startup | final),
        "events": events,
    }
