"""Untimed diagnostic control of only this owned GIL server's switch interval."""

import json
import os
import sys
import time
from pathlib import Path

_ALLOWED = (0.005, 0.0005)


def apply_requested():
    control = Path(os.environ["DIAG_INTERVAL_CONTROL"])
    request = json.loads(control.read_text())
    target = request["interval_s"]
    if target not in _ALLOWED or not sys._is_gil_enabled():
        raise RuntimeError("unsupported interval or non-GIL server")
    before = sys.getswitchinterval()
    if request["sequence"] == -1 and before != 0.005:
        raise RuntimeError("stock baseline interval was not the predeclared 5 ms")
    if before != target:
        sys.setswitchinterval(target)
    actual = sys.getswitchinterval()
    if actual != target:
        raise RuntimeError("actual interval does not match requested intervention")
    row = {
        "pid": os.getpid(),
        "sequence": request["sequence"],
        "requested_s": target,
        "before_s": before,
        "actual_s": actual,
        "gil_enabled": sys._is_gil_enabled(),
        "wall_ns": time.time_ns(),
    }
    directory = Path(os.environ["DIAG_INTERVAL_ATTEST"])
    with (directory / (str(os.getpid()) + ".jsonl")).open("a") as output:
        output.write(json.dumps(row) + "\n")
