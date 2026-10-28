"""Validate read-only Darwin thread CPU clocks before any native timing."""

import argparse
import json
import threading
import time
from pathlib import Path

from collector.thread_clock import read


def calibrate():
    current = threading.current_thread()
    python0 = time.thread_time_ns()
    before = read(current)
    until = time.thread_time_ns() + 80_000_000
    while time.thread_time_ns() < until:
        pass
    after = read(current)
    python1 = time.thread_time_ns()
    mach = sum(after[k] - before[k] for k in ("user_ns", "system_ns"))
    ratio = mach / (python1 - python0)
    if not 0.8 < ratio < 1.2:
        raise RuntimeError("current-thread CPU clocks disagree")
    go = threading.Event()
    done = threading.Event()
    release = threading.Event()
    ready = threading.Barrier(3)
    reports = {}

    def busy():
        ready.wait()
        go.wait()
        start = time.thread_time_ns()
        while time.thread_time_ns() - start < 80_000_000:
            pass
        reports["busy_clock_ns"] = time.thread_time_ns() - start
        done.set()
        release.wait()

    def idle():
        ready.wait()
        release.wait()

    workers = [threading.Thread(target=busy), threading.Thread(target=idle)]
    for thread in workers:
        thread.start()
    try:
        ready.wait(timeout=3)
        pre = [read(t) for t in workers]
        go.set()
        if not done.wait(3):
            raise RuntimeError("calibration busy thread did not finish")
        post = [read(t) for t in workers]
        deltas = [
            sum(b[k] - a[k] for k in ("user_ns", "system_ns"))
            for a, b in zip(pre, post, strict=True)
        ]
        if (
            not 0.8 < deltas[0] / reports["busy_clock_ns"] < 1.2
            or not 0 <= deltas[1] < deltas[0] / 10
        ):
            raise RuntimeError("busy/idle clock control failed")
    finally:
        go.set()
        release.set()
        for thread in workers:
            thread.join(timeout=3)
        if any(t.is_alive() for t in workers):
            raise RuntimeError("calibration threads leaked")
    return {
        "passed": True,
        "current_mach_cpu_ns": mach,
        "current_python_cpu_ns": python1 - python0,
        "current_ratio": ratio,
        "busy_mach_cpu_ns": deltas[0],
        "busy_python_cpu_ns": reports["busy_clock_ns"],
        "idle_mach_cpu_ns": deltas[1],
        "native_ids_verified": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = calibrate()
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
