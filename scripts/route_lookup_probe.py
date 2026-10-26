"""FT routing mechanism microprobe; not socket latency or candidate qualification."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import sys
import sysconfig
import threading
import time
from pathlib import Path
from types import MappingProxyType

STRATEGIES = ["original", "bound-shared", "local-proxy", "local-dict"]
SCHEDULE = STRATEGIES + STRATEGIES[::-1]


def bind_lookup(app, strategy, *, fallback=None):
    original = app._match if fallback is None else fallback
    shared = app._plan.router.literal
    if strategy == "bound-shared":
        literal = shared
    elif strategy == "local-proxy":
        literal = MappingProxyType(dict(shared))
    elif strategy == "local-dict":
        literal = dict(shared)
    else:
        raise ValueError("unsupported strategy")
    assert all(literal[key] is value for key, value in shared.items())

    def lookup(method, path):
        hit = literal.get((method, path))
        if hit is not None:
            return hit, [], ()
        return original(method, path)

    return lookup, {
        "same_route_values": True,
        "owns_mapping": literal is not shared,
        "mapping_id": id(literal),
        "mapping_type": type(literal).__name__,
    }


def percentile(values, q):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--batches", type=int, default=96)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    assert args.threads == 16 and args.batches > 0 and args.batch_size > 0
    assert os.environ.get("PYTHON_GIL") is None and sys._xoptions.get("gil") is None
    assert sysconfig.get_config_var("Py_GIL_DISABLED") and not sys._is_gil_enabled()
    args.output.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location("probe_workload", args.application)
    assert spec is not None and spec.loader is not None
    workload = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = workload
    spec.loader.exec_module(workload)
    app = workload.app
    app._compile()
    import dexpot

    module_path = Path(dexpot.__file__).parent
    assert "site-packages" in module_path.parts, "use a frozen installed artifact"
    manifest = {
        "scope": "routing-only FT mechanism microprobe; no network, lifecycle or candidate qualification",
        "candidate_qualified": False,
        "schedule": SCHEDULE,
        "threads": args.threads,
        "batches_per_thread": args.batches,
        "lookups_per_batch": args.batch_size,
        "path_policy": "fresh non-interned path on every call, four unchanged workload routes",
        "warmup_per_strategy": 256,
        "python": sys.version,
        "gil_enabled_before": sys._is_gil_enabled(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "dexpot": importlib.metadata.version("dexpot"),
        "msgspec": importlib.metadata.version("msgspec"),
        "app_source_sha256": hashlib.sha256((module_path / "app.py").read_bytes()).hexdigest(),
        "workload_sha256": hashlib.sha256(args.application.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "gc_policy": "unchanged",
        "notes": "Batch wall/CPU percentiles are not per-request/client latency percentiles.",
    }
    with (args.output / "predeclared.json").open("x") as out:
        json.dump(manifest, out, indent=2)
    barrier = threading.Barrier(args.threads + 1, timeout=60)
    lock = threading.Lock()
    rows, errors = [], []

    def worker(index):
        try:
            path = ["/flat", "/nested", "/cpu", "/io"][index % 4]
            expected = app._match("GET", path)[0]
            original = app._match
            lookups = {"original": original}
            bindings = {}
            for strategy in STRATEGIES[1:]:
                lookups[strategy], bindings[strategy] = bind_lookup(app, strategy)
            for round_id, strategy in enumerate(SCHEDULE):
                lookup = lookups[strategy]
                for _ in range(256):
                    result = lookup("GET", (path + "?")[:-1])
                    assert result[0] is expected and result[1:] == ([], ())
                batches = []
                barrier.wait()
                for _ in range(args.batches):
                    wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
                    for _ in range(args.batch_size):
                        result = lookup("GET", (path + "?")[:-1])
                        assert result[0] is expected and result[1:] == ([], ())
                    batches.append([time.perf_counter_ns() - wall, time.thread_time_ns() - cpu])
                with lock:
                    rows.append(
                        {
                            "thread": index,
                            "round": round_id,
                            "strategy": strategy,
                            "route": path,
                            "bindings": bindings,
                            "batches": batches,
                            "good": args.batches * args.batch_size,
                        }
                    )
                barrier.wait()
        except BaseException as exc:
            with lock:
                errors.append({"thread": index, "error": repr(exc)})
            barrier.abort()

    workers = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.threads)]
    for thread in workers:
        thread.start()
    trials = []
    try:
        for round_id, strategy in enumerate(SCHEDULE):
            start = time.perf_counter_ns()
            barrier.wait()
            barrier.wait()
            elapsed = time.perf_counter_ns() - start
            current = [row for row in rows if row["round"] == round_id]
            assert (
                len(current) == args.threads
                and sum(row["good"] for row in current)
                == args.threads * args.batches * args.batch_size
            )
            with (args.output / f"round-{round_id}.json").open("x") as out:
                json.dump(current, out)
            walls = [batch[0] for row in current for batch in row["batches"]]
            cpus = [batch[1] for row in current for batch in row["batches"]]
            trial = {
                "round": round_id,
                "strategy": strategy,
                "lookups": sum(row["good"] for row in current),
                "round_wall_including_warmup_and_barriers_ns": elapsed,
                "batch_wall_p50_ns": percentile(walls, 0.5),
                "batch_wall_p99_ns": percentile(walls, 0.99),
                "batch_cpu_p50_ns": percentile(cpus, 0.5),
                "batch_cpu_p99_ns": percentile(cpus, 0.99),
                "thread_cpu_sum_ns": sum(cpus),
            }
            trials.append(trial)
            print(json.dumps(trial), flush=True)
    finally:
        for thread in workers:
            thread.join(timeout=5)
    result = {
        "status": "microprobe-complete"
        if len(trials) == len(SCHEDULE) and not errors
        else "microprobe-invalid",
        "candidate_qualified": False,
        "gil_enabled_after": sys._is_gil_enabled(),
        "trials": trials,
        "errors": errors,
        "live_threads": sum(t.is_alive() for t in workers),
    }
    with (args.output / "results.json").open("x") as out:
        json.dump(result, out, indent=2)
    assert (
        result["status"] == "microprobe-complete"
        and not result["gil_enabled_after"]
        and result["live_threads"] == 0
    )


if __name__ == "__main__":
    main()
