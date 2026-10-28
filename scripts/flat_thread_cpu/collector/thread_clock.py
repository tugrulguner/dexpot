"""Read-only CPU counters for known-live fixed Darwin server threads."""

import ctypes
import ctypes.util
import threading
import time

lib = ctypes.CDLL(ctypes.util.find_library("System"))
lib.pthread_mach_thread_np.argtypes = [ctypes.c_void_p]
lib.pthread_mach_thread_np.restype = ctypes.c_uint
lib.thread_info.argtypes = [
    ctypes.c_uint,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_uint),
]
lib.thread_info.restype = ctypes.c_int


class Basic(ctypes.Structure):
    _fields_ = [
        (k, ctypes.c_int)
        for k in (
            "user_sec",
            "user_usec",
            "system_sec",
            "system_usec",
            "cpu_usage",
            "policy",
            "run_state",
            "flags",
            "suspend_count",
            "sleep_time",
        )
    ]


class Identifier(ctypes.Structure):
    _fields_ = [(k, ctypes.c_uint64) for k in ("thread_id", "thread_handle", "dispatch_qaddr")]


assert ctypes.sizeof(Basic) == 40 and ctypes.sizeof(Identifier) == 24


def read(thread):
    if not thread.is_alive() or thread.ident is None or thread.native_id is None:
        raise RuntimeError("thread is not live")
    # Borrowed pthread port: never deallocate or change policy.
    port = lib.pthread_mach_thread_np(ctypes.c_void_p(thread.ident))
    if not port:
        raise RuntimeError("missing Mach thread port")
    values = []
    for flavor, struct, words in ((3, Basic, 10), (4, Identifier, 6)):
        value = struct()
        count = ctypes.c_uint(words)
        result = lib.thread_info(
            port,
            flavor,
            ctypes.cast(ctypes.byref(value), ctypes.POINTER(ctypes.c_int)),
            ctypes.byref(count),
        )
        if result or count.value != words:
            raise RuntimeError(f"thread_info failed {result}, count {count.value}")
        values.append(value)
    basic, identifier = values
    if identifier.thread_id != thread.native_id:
        raise RuntimeError("native thread identity mismatch")
    return {
        "name": thread.name,
        "native_id": thread.native_id,
        "ident": thread.ident,
        "user_ns": basic.user_sec * 1_000_000_000 + basic.user_usec * 1000,
        "system_ns": basic.system_sec * 1_000_000_000 + basic.system_usec * 1000,
    }


def snapshot(owner, app):
    start = time.monotonic_ns()
    workers = [
        t
        for t in threading.enumerate()
        if getattr(getattr(t, "_target", None), "__self__", None) is app
        and getattr(getattr(t, "_target", None), "__name__", None) == "_worker_gil"
    ]
    if owner is None or not owner.thread.is_alive() or len(workers) != 16:
        raise RuntimeError(f"fixed pool mismatch: {len(workers)} workers")
    rows = []
    for role, threads in (
        ("main", [threading.main_thread()]),
        ("owner", [owner.thread]),
        ("worker", workers),
    ):
        for thread in threads:
            row = read(thread)
            row["role"] = role
            rows.append(row)
    if len({r["native_id"] for r in rows}) != 18:
        raise RuntimeError("fixed thread identity collision")
    return {
        "start_ns": start,
        "end_ns": time.monotonic_ns(),
        "owner_native_id": owner.thread.native_id,
        "threads": rows,
    }
