"""Event-driven child creation detection for an external resource observer.

Observe target fork events, including children that exit between samples.
Any registration/event error raises rather than assuming no child existed.
"""

import contextlib
import select
import sys

import psutil


class ForkGuard:
    def __init__(self, pid):
        self.pid = pid
        self.queue = select.kqueue()
        self.forked = False
        self.events = 0
        try:
            event = select.kevent(
                pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_FORK | select.KQ_NOTE_EXIT,
            )
            self.queue.control([event], 0, 0)
            # Register first so there is no gap between initial inventory and
            # subsequent event observation. Existing children also fail closed.
            self.forked = bool(psutil.Process(pid).children())
        except BaseException:
            self.queue.close()
            raise

    def count(self):
        for event in self.queue.control(None, 16, 0):
            self.events += 1
            if event.flags & select.KQ_EV_ERROR:
                raise RuntimeError(f"fork observer error for {self.pid}: {event.data}")
            if event.fflags & select.KQ_NOTE_FORK:
                self.forked = True
        # Sticky failure detects transient forks more strongly than snapshots.
        return int(self.forked)

    def close(self):
        self.queue.close()


class ChildrenObserver:
    """Keep native child-budget detection out of repeated global PID walks."""

    def __init__(self):
        self.guards = {}

    def children(self, process):
        if sys.platform != "darwin":
            return len(process.children())
        if process.pid not in self.guards:
            self.guards[process.pid] = ForkGuard(process.pid)
        return self.guards[process.pid].count()

    def close(self):
        # Attempt every close even if a prior descriptor cleanup fails.
        with contextlib.ExitStack() as cleanup:
            for guard in self.guards.values():
                cleanup.callback(guard.close)
