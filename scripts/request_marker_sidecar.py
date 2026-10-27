"""Opt-in diagnostic markers. Install once, never replace module globals per request."""

from __future__ import annotations

import importlib
import json
import os
import re
import threading
import time
from pathlib import Path

HEADER = "X-Dexpot-Diag-Id"
_tls = threading.local()
_lock = threading.Lock()
_buffers: dict[int, dict] = {}
_DIR: Path | None = None
_LIMIT = 4096


def _emit(marker, event, stamp=None):
    if stamp is None:
        stamp = (time.time_ns() // 1000, time.monotonic_ns(), time.thread_time_ns())
    row = {
        "id": marker,
        "event": event,
        "wall_us": stamp[0],
        "mono_ns": stamp[1],
        "thread_cpu_ns": stamp[2],
    }
    context = getattr(_tls, "context", None)
    if context is None:
        context = {"rows": [], "dropped": 0, "lock": threading.Lock()}
        _tls.context = context
        with _lock:
            _buffers[threading.get_ident()] = context
    # Lock is per-thread and only reached for sampled markers, not every request.
    with context["lock"]:
        if len(context["rows"]) >= _LIMIT:
            context["dropped"] += 1
        else:
            context["rows"].append(row)


def flush():
    if _DIR is None:
        return
    with _lock:
        contexts = list(_buffers.items())
    for tid, context in contexts:
        with context["lock"]:
            rows, context["rows"] = context["rows"], []
            dropped, context["dropped"] = context["dropped"], 0
        if rows or dropped:
            with (_DIR / f"server-{os.getpid()}-{tid}.jsonl").open("a") as output:
                for row in rows:
                    output.write(json.dumps(row, separators=(",", ":")) + "\n")
                output.write(json.dumps({"event": "flush_summary", "dropped": dropped}) + "\n")


def install(app):
    global _DIR
    directory = os.environ.get("DIAG_DIR", "")
    if not directory or not Path(directory).is_absolute() or not Path(directory).is_dir():
        raise ValueError("DIAG_DIR must be an absolute existing directory")
    _DIR = Path(directory)
    cls = type(app)
    module = importlib.import_module(cls.__module__)
    original_read = module.read_request
    original_send = cls._send
    if getattr(original_read, "_diagnostic_marker", False):
        raise RuntimeError("markers already installed")

    def read(*args, **kwargs):
        _tls.sample = None
        started = (time.time_ns() // 1000, time.monotonic_ns(), time.thread_time_ns())
        previous = getattr(_tls, "last_send", None)
        if not args or previous is None or previous[0] is not args[0]:
            previous = None
        request, rest = original_read(*args, **kwargs)
        marker = request.headers.get("x-dexpot-diag-id")
        if marker and re.fullmatch(r"[0-9]{1,12}-[0-9]{1,3}-[0-9]{1,12}", marker):
            _tls.sample = marker
            _emit(marker, "Sparsed")
            _emit(marker, "Sread_entry", started)
            if previous is not None:
                _emit(marker, "Sprevious_send_return", previous[1])
        return request, rest

    def send(
        conn,
        status,
        out,
        *,
        keep_alive,
        version="HTTP/1.1",
        extra_headers=(),
        suppress_body=False,
        content_type="application/json",
    ):
        marker = getattr(_tls, "sample", None)
        if marker:
            extra_headers = (*extra_headers, (HEADER, marker))
            _emit(marker, "Ssend_entry")
        try:
            result = original_send(
                conn,
                status,
                out,
                keep_alive=keep_alive,
                version=version,
                extra_headers=extra_headers,
                suppress_body=suppress_body,
                content_type=content_type,
            )
            returned = (time.time_ns() // 1000, time.monotonic_ns(), time.thread_time_ns())
            _tls.last_send = (conn, returned)
            if marker:
                _emit(marker, "Ssend_return", returned)
            return result
        finally:
            _tls.sample = None

    read._diagnostic_marker = True
    module.read_request = read
    cls._send = staticmethod(send)
