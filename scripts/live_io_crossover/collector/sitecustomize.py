"""Diagnostic-only classic/shared backend controls, installed before compilation."""

import os

from dexpot import Dex

original = Dex.serve


def serving(self, *args, **kwargs):
    saved = []

    def owner():
        if not saved:
            current = getattr(self, "_gil_io", None)
            if current is not None:
                saved.append(current)
        return saved[0] if saved else None

    def status():
        held = owner()
        with self._cond:
            active = len(self._active_connections)
            queued = len(self._work)
            raw = next(iter(self._active_connections)) if active == 1 else None
        owned = False
        if held is not None and raw is not None:
            with held._lock:
                owned = raw in held._states
        return {
            "pid": os.getpid(),
            "mode": getattr(self, "_gil_io", None) is not None,
            "connection_owned": owned,
            "active": active,
            "queued": queued,
        }

    def configure(value):
        held = owner()
        with self._cond:
            if held is None or len(self._active_connections) != 1 or self._work:
                return ({"detail": "not quiescent"}, 409)
            # Only future connections read this pointer; this control connection
            # retains its already selected local channel through response/close.
            self._gil_io = held if value else None
        return status()

    self.get("/_wake_diag/status")(status)
    self.get("/_wake_diag/off")(lambda: configure(False))
    self.get("/_wake_diag/on")(lambda: configure(True))
    try:
        return original(self, *args, **kwargs)
    finally:
        if saved:
            # Required if the final diagnostic window selected the raw backend.
            saved[0].close()


Dex.serve = serving
