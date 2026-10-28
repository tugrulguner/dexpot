import atexit
import json
import os
import sys
import threading
import time

_orig = time.sleep
_cap = 200000
_rows = []
_drops = 0
_lock = threading.Lock()


def _wrapped(secs):
    global _drops
    f = sys._getframe(1)
    if f.f_code.co_filename.endswith("application.py") and f.f_code.co_name == "io":
        start = time.monotonic_ns()
        cpu = time.thread_time_ns()
        tid = threading.get_ident()
        try:
            return _orig(secs)
        finally:
            row = {
                "requested_secs": secs,
                "elapsed_ns": time.monotonic_ns() - start,
                "thread_cpu_ns": time.thread_time_ns() - cpu,
                "thread_id": tid,
            }
            with _lock:
                if len(_rows) < _cap:
                    _rows.append(row)
                else:
                    _drops += 1
    return _orig(secs)


time.sleep = _wrapped


def _dump():
    path = (
        os.environ.get("IO_WAIT_DIAGNOSTIC_PATH")
        if os.path.basename(sys.argv[0]) == "application.py"
        else None
    )
    if path:
        with open(path, "x") as f:
            json.dump({"pid": os.getpid(), "records": _rows, "drops": _drops}, f)


atexit.register(_dump)
