"""Bounded GIL idle-socket readiness handoff; workers own only readable work."""

from __future__ import annotations

import contextlib
import heapq
import itertools
import selectors
import socket
import threading
import time
from collections import deque
from typing import Any


class GILIdleHub:
    def __init__(self, owner: Any, pool: int, queue_limit: int, connection_limit: int) -> None:
        self.owner = owner
        self.pool = pool
        self.queue_limit = queue_limit
        self.connection_limit = connection_limit
        self.lock = threading.Lock()
        self.states: dict[socket.socket, str] = {}
        self.commands: dict[socket.socket, tuple[str, bytes, float | None, float | None]] = {}
        self.idle: dict[socket.socket, tuple[bytes, float, float]] = {}
        self.deadlines: list[tuple[float, int, socket.socket]] = []
        self.serial = itertools.count()
        self.ready: deque[tuple[socket.socket, bytes, float | None]] = deque()
        self.stopping = threading.Event()
        self.closed = False
        self.outstanding = 0
        self.wake_pending = False
        try:
            with contextlib.ExitStack() as cleanup:
                self.selector = selectors.DefaultSelector()
                cleanup.callback(self.selector.close)
                self.reader, self.writer = socket.socketpair()
                cleanup.callback(self.reader.close)
                cleanup.callback(self.writer.close)
                self.reader.setblocking(False)
                self.writer.setblocking(False)
                self.selector.register(self.reader, selectors.EVENT_READ)
                self.thread = threading.Thread(target=self.run, name="dexpot-gil-idle", daemon=True)
                self.thread.start()
                cleanup.pop_all()
        except BaseException:
            self.closed = True
            self.stopping.set()
            raise

    def wake(self) -> None:
        with self.lock:
            if self.wake_pending or self.closed:
                return
            self.wake_pending = True
        with contextlib.suppress(OSError):
            self.writer.send(b"\x00")

    def admit(self, conn: socket.socket, buf: bytes) -> bool:
        with self.lock:
            if self.closed or self.stopping.is_set() or len(self.states) >= self.connection_limit:
                return False
            self.states[conn] = "parking"
            now = time.monotonic()
            head_deadline = now + self.owner.limits.head_read_seconds if not buf else None
            deadline = (
                min(now + self.owner.limits.idle_read_seconds, head_deadline)
                if head_deadline is not None
                else None
            )
            self.commands[conn] = ("park", buf, deadline, head_deadline)
        self.wake()
        return True

    def started(self, conn: socket.socket) -> None:
        with self.lock:
            if conn not in self.states:
                self.outstanding += 1
            self.states[conn] = "active"
            needs_wake = bool(self.ready)
        if needs_wake:
            self.wake()

    def park(
        self,
        conn: socket.socket,
        buf: bytes,
        *,
        deadline: float | None = None,
        head_deadline: float | None = None,
    ) -> None:
        with self.lock:
            if self.states.get(conn) in ("ready", "queued", "active"):
                self.outstanding -= 1
            if self.closed or self.stopping.is_set():
                self.states.pop(conn, None)
                with contextlib.suppress(OSError):
                    conn.close()
                return
            self.states[conn] = "parking"
            self.commands[conn] = ("park", buf, deadline, head_deadline)
        self.wake()

    def release(self, conn: socket.socket) -> None:
        with self.lock:
            if self.states.get(conn) in ("ready", "queued", "active"):
                self.outstanding -= 1
            if self.closed:
                self.states.pop(conn, None)
                with contextlib.suppress(OSError):
                    conn.close()
                return
            self.states[conn] = "closing"
            self.commands[conn] = ("close", b"", None, None)
        self.wake()

    def unregister(self, conn: socket.socket) -> None:
        with contextlib.suppress(KeyError, ValueError, OSError):
            self.selector.unregister(conn)
        self.idle.pop(conn, None)

    def close(self, conn: socket.socket) -> None:
        self.unregister(conn)
        if self.states.pop(conn, None) in ("ready", "queued", "active"):
            self.outstanding -= 1
        self.commands.pop(conn, None)
        with contextlib.suppress(OSError):
            conn.close()

    def make_ready(self, conn: socket.socket, buf: bytes, head_deadline: float | None) -> None:
        # Reserve execution capacity plus the bounded wait queue, even before
        # newly notified workers have had a scheduling turn.
        if self.outstanding >= self.pool + self.queue_limit:
            self.unregister(conn)
            with contextlib.suppress(OSError):
                conn.settimeout(0.001)
                self.owner._reject_overload(conn)
            self.close(conn)
            return
        self.states[conn] = "ready"
        self.outstanding += 1
        self.ready.append((conn, buf, head_deadline))

    def flush_ready(self) -> None:
        with self.owner._cond:
            while self.ready and len(self.owner._work) < self.queue_limit:
                conn, buf, head_deadline = self.ready.popleft()
                if self.states.get(conn) != "ready":
                    continue
                self.states[conn] = "queued"
                self.owner._work.append((conn, buf, head_deadline))
                self.owner._cond.notify()

    def run(self) -> None:
        try:
            while not self.stopping.is_set():
                with self.lock:
                    commands = list(self.commands.items())
                    self.commands.clear()
                    for conn, (action, buf, deadline, head_deadline) in commands:
                        if action == "close":
                            self.close(conn)
                            continue
                        if self.states.get(conn) != "parking":
                            continue
                        self.unregister(conn)
                        if buf:
                            self.make_ready(conn, buf, head_deadline)
                        else:
                            try:
                                self.selector.register(conn, selectors.EVENT_READ)
                            except (OSError, ValueError, KeyError):
                                self.close(conn)
                                continue
                            self.states[conn] = "idle"
                            now = time.monotonic()
                            if head_deadline is None:
                                head_deadline = now + self.owner.limits.head_read_seconds
                            if deadline is None:
                                deadline = min(
                                    now + self.owner.limits.idle_read_seconds, head_deadline
                                )
                            self.idle[conn] = (buf, deadline, head_deadline)
                            heapq.heappush(self.deadlines, (deadline, next(self.serial), conn))
                    # Compact stale entries at a hard connection-derived bound.
                    if len(self.deadlines) > 2 * self.connection_limit:
                        self.deadlines = [
                            (deadline, next(self.serial), conn)
                            for conn, (_, deadline, _) in self.idle.items()
                        ]
                        heapq.heapify(self.deadlines)
                    now = time.monotonic()
                    while self.deadlines:
                        deadline, _, conn = self.deadlines[0]
                        item = self.idle.get(conn)
                        if item is None or item[1] != deadline:
                            heapq.heappop(self.deadlines)
                            continue
                        if deadline > now:
                            break
                        heapq.heappop(self.deadlines)
                        # Preserve best-effort idle timeout framing.
                        with contextlib.suppress(OSError):
                            conn.settimeout(0.001)
                            self.owner._send(
                                conn, 408, b'{"detail":"request timeout"}', keep_alive=False
                            )
                        self.close(conn)
                    self.flush_ready()
                    timeout = (
                        min(0.5, max(0.0, self.deadlines[0][0] - time.monotonic()))
                        if self.deadlines
                        else 0.5
                    )
                events = self.selector.select(timeout)
                with self.lock:
                    for key, _ in events:
                        conn = key.fileobj
                        if not isinstance(conn, socket.socket):
                            continue
                        if conn is self.reader:
                            while True:
                                try:
                                    if not self.reader.recv(4096):
                                        break
                                except BlockingIOError:
                                    break
                            self.wake_pending = False
                            continue
                        if self.states.get(conn) != "idle":
                            continue
                        buf, deadline, head_deadline = self.idle[conn]
                        if time.monotonic() >= deadline:
                            with contextlib.suppress(OSError):
                                conn.settimeout(0.001)
                                self.owner._send(
                                    conn, 408, b'{"detail":"request timeout"}', keep_alive=False
                                )
                            self.close(conn)
                            continue
                        self.unregister(conn)
                        self.make_ready(conn, buf, head_deadline)
                    self.flush_ready()
        finally:
            with self.lock:
                self.closed = True
                for conn, state in list(self.states.items()):
                    if state != "active":
                        self.close(conn)
                self.commands.clear()
                self.ready.clear()
                self.selector.close()
                self.reader.close()
                self.writer.close()

    def stop(self) -> None:
        self.stopping.set()
        self.wake()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("GIL idle readiness owner failed to stop")
