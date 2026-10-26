"""Sampled server-side stage attribution. Never acceptance timing or a causal verdict."""

import functools
import json
import os
import sys
import threading
import time
from pathlib import Path

PATHS = {"/flat", "/nested", "/cpu", "/io"}
STAGES = ("read", "match", "handler", "encode", "send")


def snapshot(path, total, spans):
    used = [sum(pair[index] for pair in spans.values()) for index in (0, 1)]
    return {
        "path": path,
        "total": list(total),
        **{name: list(spans.get(name, (0, 0))) for name in STAGES},
        "residual": [max(0, total[index] - used[index]) for index in (0, 1)],
        "overlap_or_clock_error": any(used[index] > total[index] for index in (0, 1)),
    }


def instrument_application(source):
    assert source.count("app = Dex()") == 1
    result = source.replace(
        "app = Dex()",
        "from lifecycle_stage_probe import install\ntimed_handler, stage_report = install(Dex)\n\napp = Dex()",
    )
    for name in ("flat", "nested", "cpu", "io"):
        marker = f"def {name}()"
        assert result.count(marker) == 1
        result = result.replace(marker, "@timed_handler\n" + marker)
    marker = '    app.serve("127.0.0.1", args.port)'
    assert result.count(marker) == 1
    return result.replace(
        marker,
        '    try:\n        app.serve("127.0.0.1", args.port)\n    finally:\n        stage_report()',
    )


def install(Dex, *, sample_every=32, cap_per_thread=4000):
    from dexpot._plans import EndpointPlan

    module = sys.modules[Dex.__module__]
    local = threading.local()
    states = []
    lock = threading.Lock()
    originals = {
        "process": Dex._process,
        "read": module.read_request,
        "match": Dex._match,
        "encode": EndpointPlan.encode,
        "send": Dex._send,
    }

    def state():
        current = getattr(local, "current", None)
        if current is None:
            current = {
                "thread": threading.get_ident(),
                "process_calls": 0,
                "selected": False,
                "path": None,
                "spans": {},
                "calls": {},
                "handler_depth": 0,
                "sampled": 0,
                "dropped": 0,
                "records": [],
            }
            local.current = current
            with lock:
                states.append(current)
        return current

    def measured(stage, fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            current = state()
            if not current["selected"]:
                return fn(*args, **kwargs)
            if stage == "handler" and current["handler_depth"]:
                return fn(*args, **kwargs)
            if stage == "handler":
                current["handler_depth"] = 1
            start, cpu = time.perf_counter_ns(), time.thread_time_ns()
            try:
                return fn(*args, **kwargs)
            finally:
                wall, spent = time.perf_counter_ns() - start, time.thread_time_ns() - cpu
                prior = current["spans"].get(stage, (0, 0))
                current["spans"][stage] = (prior[0] + wall, prior[1] + spent)
                current["calls"][stage] = current["calls"].get(stage, 0) + 1
                if stage == "handler":
                    current["handler_depth"] = 0

        return wrapped

    read = measured("read", originals["read"])

    def read_request(*args, **kwargs):
        result = read(*args, **kwargs)
        state()["path"] = result[0].path
        return result

    def process(self, conn, buf):
        current = state()
        current["process_calls"] += 1
        current["selected"] = current["process_calls"] % sample_every == 0
        current["path"], current["spans"], current["calls"] = None, {}, {}
        if not current["selected"]:
            return originals["process"](self, conn, buf)
        start, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            return originals["process"](self, conn, buf)
        finally:
            total = (time.perf_counter_ns() - start, time.thread_time_ns() - cpu)
            if current["path"] in PATHS:
                current["sampled"] += 1
                if len(current["records"]) < cap_per_thread:
                    row = snapshot(current["path"], total, current["spans"])
                    row["calls"] = dict(current["calls"])
                    current["records"].append(row)
                else:
                    current["dropped"] += 1
            current["selected"] = False

    module.read_request = read_request
    Dex._match = measured("match", originals["match"])
    EndpointPlan.encode = measured("encode", originals["encode"])
    Dex._send = staticmethod(measured("send", originals["send"]))
    Dex._process = process

    def timed_handler(fn):
        return measured("handler", fn)

    def report():
        path = Path.cwd() / f"stage-report-{os.getpid()}.json"
        payload = {
            "pid": os.getpid(),
            "sample_every": sample_every,
            "cap_per_thread": cap_per_thread,
            "scope": "instrumented sampled server spans; read includes socket receive; residual excludes all named stages; not client latency or acceptance",
            "threads": states,
        }
        with path.open("x") as stream:
            json.dump(payload, stream)
        print("STAGE_REPORT", str(path), flush=True)
        module.read_request = originals["read"]
        Dex._match = originals["match"]
        EndpointPlan.encode = originals["encode"]
        Dex._send = staticmethod(originals["send"])
        Dex._process = originals["process"]
        return payload

    return timed_handler, report
