"""Bounded sampled Python-observed request stages, not syscall/GIL attribution."""

import os
import time

from dexpot import Dex
from dexpot._gil_io import SocketIO, SocketOwner

FLAT = b'{"id":7,"name":"item-7","price":9.99}'
CONNECTION_CAP = 128
SAMPLE_CAP = 10000
connections = {}
pending = {}
rows = []
errors = set()
dropped = 0
prepared = 0

original_wait = SocketOwner.wait_request
original_send = SocketOwner.sendall
original_enqueue = SocketIO._enqueue
original_advance = SocketIO._advance
original_finish = SocketIO._finish
original_serve = Dex.serve


def entry(raw):
    global dropped
    item = connections.get(raw)
    if item is None:
        if len(connections) >= CONNECTION_CAP:
            dropped += 1
            return None
        item = {"connection": len(connections) + 1, "waits": 0, "prepared": 0, "sample": None}
        connections[raw] = item
    return item


def wait_request(self, *args, **kwargs):
    item = entry(self._conn)
    if item is not None:
        item["waits"] += 1
        item["sample"] = None
    result = original_wait(self, *args, **kwargs)
    if item is not None and item["waits"] % 64 == 0:
        state = self._state
        if state.data and not state.closed and state.error is None:
            previous = state.outgoing.finished_at if state.outgoing is not None else 0
            item["sample"] = {
                "connection": item["connection"],
                "sequence": item["waits"],
                "available_ns": int(state.available_at * 1e9),
                "previous_finished_ns": int(previous * 1e9),
                "worker_ns": time.monotonic_ns(),
            }
    return result


def sendall(self, data):
    global prepared
    item = entry(self._conn)
    if data.endswith(FLAT):
        prepared += 1
        if item is not None:
            item["prepared"] += 1
            sample = item["sample"]
            if sample is not None and sample["sequence"] != item["prepared"]:
                errors.add("request/response sequence mismatch")
    elif item is not None:
        item["sample"] = None
    return original_send(self, data)


def enqueue(self, task):
    global dropped
    item = connections.get(task.conn)
    sample = item["sample"] if item is not None else None
    if task.operation == "sendall" and task.pipeline and sample is not None and item is not None:
        if len(pending) >= CONNECTION_CAP:
            dropped += 1
        else:
            sample["enqueue_ns"] = time.monotonic_ns()
            # _Call is slotted and unhashable: retain the exact object by id.
            pending[id(task)] = (task, sample)
        item["sample"] = None
    return original_enqueue(self, task)


def advance(self, task):
    found = pending.get(id(task))
    if found is not None:
        assert found[0] is task
        found[1].setdefault("advance_ns", time.monotonic_ns())
    return original_advance(self, task)


def finish(self, task, *args, **kwargs):
    global dropped
    result = original_finish(self, task, *args, **kwargs)
    found = pending.pop(id(task), None)
    if found is not None:
        assert found[0] is task
        sample = found[1]
        sample["finished_ns"] = int(task.finished_at * 1e9)
        sample["error"] = repr(task.error) if task.error is not None else None
        if "advance_ns" not in sample:
            errors.add("completion without first advance")
        if len(rows) >= SAMPLE_CAP:
            dropped += 1
        else:
            rows.append(sample)
    return result


SocketOwner.wait_request = wait_request
SocketOwner.sendall = sendall
SocketIO._enqueue = enqueue
SocketIO._advance = advance
SocketIO._finish = finish


def serving(self, *args, **kwargs):
    def quiescent():
        with self._cond:
            return len(self._active_connections) == 1 and not self._work

    def status():
        owner = self._gil_io
        with self._cond:
            active = len(self._active_connections)
            queued = len(self._work)
            raw = next(iter(self._active_connections)) if active == 1 else None
        with owner._lock:
            owned = raw in owner._states if raw is not None else False
        return {
            "pid": os.getpid(),
            "mode": True,
            "connection_owned": owned,
            "active": active,
            "queued": queued,
        }

    def dump():
        if not quiescent() or pending:
            return ({"detail": "not quiescent"}, 409)
        return {
            "pid": os.getpid(),
            "prepared": prepared,
            "dropped": dropped,
            "pending": len(pending),
            "errors": list(errors),
            "rows": list(rows),
            "connections": [
                {"connection": v["connection"], "prepared": v["prepared"], "waits": v["waits"]}
                for v in connections.values()
            ],
        }

    def reset():
        global dropped, prepared
        if not quiescent() or pending:
            return ({"detail": "not quiescent"}, 409)
        connections.clear()
        rows.clear()
        errors.clear()
        dropped = 0
        prepared = 0
        return {"reset": True, "pid": os.getpid()}

    self.get("/_wake_diag/status")(status)
    self.get("/_wake_diag/on")(status)
    self.get("/_stage_diag/dump")(dump)
    self.get("/_stage_diag/reset")(reset)
    return original_serve(self, *args, **kwargs)


Dex.serve = serving
