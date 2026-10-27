"""One bounded nonblocking socket-I/O owner for a GIL handler pool."""

from __future__ import annotations

import contextlib
import errno
import queue
import selectors
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Call:
    conn: socket.socket
    operation: str
    argument: Any
    deadline: float | None
    nonblocking: bool
    done: threading.Event = field(default_factory=threading.Event)
    value: Any = None
    error: BaseException | None = None
    offset: int = 0
    fd: int = -1


class SocketIO:
    """Serialize readiness-driven I/O, not handlers, on one process-local thread."""

    def __init__(self) -> None:
        self._commands: queue.SimpleQueue[_Call] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._wake_pending = False
        self._stopping = False
        self._connections: set[socket.socket] = set()
        self._pending: dict[socket.socket, _Call] = {}
        self._selector = selectors.DefaultSelector()
        try:
            self._reader, self._writer = socket.socketpair()
            self._reader.setblocking(False)
            self._writer.setblocking(False)
            self._selector.register(self._reader, selectors.EVENT_READ, None)
            self.thread = threading.Thread(target=self._run, name="dexpot-gil-io", daemon=True)
            self.thread.start()
        except BaseException:
            self._selector.close()
            for name in ("_reader", "_writer"):
                peer = getattr(self, name, None)
                if peer is not None:
                    peer.close()
            raise

    def connection(self, conn: socket.socket) -> SocketOwner:
        timeout = conn.gettimeout()
        with self._lock:
            if self._stopping:
                raise OSError(errno.EBADF, "I/O owner is closed")
            conn.setblocking(False)
            self._connections.add(conn)
        return SocketOwner(self, conn, timeout)

    def _wake(self) -> None:
        with contextlib.suppress(OSError):
            self._writer.send(b"\0")

    def call(
        self, conn: socket.socket, operation: str, argument: Any, timeout: float | None
    ) -> Any:
        deadline = time.monotonic() + timeout if timeout is not None else None
        task = _Call(conn, operation, argument, deadline, timeout == 0)
        with self._lock:
            if self._stopping:
                if operation == "close":
                    conn.close()
                    return None
                raise OSError(errno.EBADF, "I/O owner is closed")
            self._commands.put(task)
            wake = not self._wake_pending
            self._wake_pending = True
        if wake:
            self._wake()
        task.done.wait()
        if task.error is not None:
            raise task.error
        return task.value

    def _finish(self, task: _Call, value: Any = None, error: BaseException | None = None) -> None:
        if task.fd >= 0:
            with contextlib.suppress(KeyError, ValueError, OSError):
                key = self._selector.get_key(task.fd)
                if key.data is task:
                    self._selector.unregister(task.fd)
        if self._pending.get(task.conn) is task:
            del self._pending[task.conn]
        task.value, task.error = value, error
        task.done.set()

    def _watch(self, task: _Call, event: int) -> None:
        if task.nonblocking:
            self._finish(task, error=BlockingIOError(errno.EWOULDBLOCK, "operation would block"))
            return
        try:
            task.fd = task.conn.fileno()
            if task.fd < 0:
                raise OSError(errno.EBADF, "socket closed")
            self._pending[task.conn] = task
            self._selector.register(task.conn, event, task)
        except BaseException as exc:
            self._finish(task, error=exc)

    def _advance(self, task: _Call) -> None:
        if task.done.is_set():
            return
        if task.deadline is not None and not task.nonblocking and time.monotonic() >= task.deadline:
            self._finish(task, error=TimeoutError("timed out"))
            return
        # A readiness registration is removed before another single bounded I/O turn.
        if task.fd >= 0:
            with contextlib.suppress(KeyError, ValueError, OSError):
                self._selector.unregister(task.fd)
            task.fd = -1
        try:
            if task.operation == "recv":
                self._finish(task, task.conn.recv(task.argument))
                return
            data = task.argument
            if task.offset == len(data):
                self._finish(task)
                return
            sent = task.conn.send(data[task.offset :])
            if sent == 0:
                raise ConnectionResetError("socket write returned zero")
            task.offset += sent
            if task.offset == len(data):
                self._finish(task)
                return
        except BlockingIOError:
            pass
        except BaseException as exc:
            self._finish(task, error=exc)
            return
        self._watch(
            task, selectors.EVENT_READ if task.operation == "recv" else selectors.EVENT_WRITE
        )

    def _drain_commands(self) -> None:
        while True:
            with self._lock:
                try:
                    task = self._commands.get_nowait()
                except queue.Empty:
                    self._wake_pending = False
                    return
            # Reconcile externally closed drain survivors before a descriptor can be reused.
            for previous in list(self._pending.values()):
                if previous.conn.fileno() != previous.fd:
                    self._finish(previous, error=OSError(errno.EBADF, "socket closed"))
            if task.operation == "close":
                previous = self._pending.get(task.conn)
                if previous is not None:
                    self._finish(previous, error=OSError(errno.EBADF, "socket closed"))
                error = None
                try:
                    task.conn.close()
                except BaseException as exc:
                    error = exc
                finally:
                    if task.conn.fileno() < 0:
                        with self._lock:
                            self._connections.discard(task.conn)
                    self._finish(task, error=error)
            elif task.conn in self._pending:
                self._finish(task, error=RuntimeError("overlapping operations on one connection"))
            else:
                self._advance(task)

    def _run(self) -> None:
        try:
            while True:
                self._drain_commands()
                with self._lock:
                    if self._stopping:
                        return
                now = time.monotonic()
                for task in list(self._pending.values()):
                    if task.conn.fileno() != task.fd:
                        self._finish(task, error=OSError(errno.EBADF, "socket closed"))
                    elif task.deadline is not None and now >= task.deadline:
                        self._finish(task, error=TimeoutError("timed out"))
                deadlines = [
                    task.deadline for task in self._pending.values() if task.deadline is not None
                ]
                timeout = min(0.5, max(0, min(deadlines) - time.monotonic())) if deadlines else 0.5
                for key, _events in self._selector.select(timeout):
                    if key.data is None:
                        while True:
                            try:
                                if not self._reader.recv(4096):
                                    break
                            except BlockingIOError:
                                break
                    else:
                        self._advance(key.data)
        finally:
            with self._lock:
                self._stopping = True
                connections = list(self._connections)
                self._connections.clear()
            for task in list(self._pending.values()):
                self._finish(task, error=OSError(errno.EBADF, "I/O owner stopped"))
            while True:
                try:
                    task = self._commands.get_nowait()
                except queue.Empty:
                    break
                self._finish(task, error=OSError(errno.EBADF, "I/O owner stopped"))
            for conn in connections:
                with contextlib.suppress(OSError):
                    conn.close()
            self._selector.close()
            self._reader.close()
            self._writer.close()

    def close(self, timeout: float = 1) -> None:
        with self._lock:
            self._stopping = True
        self._wake()
        self.thread.join(timeout=max(0, timeout))


class SocketOwner:
    """A connection-pinned worker's local socket facade; no extra owner thread."""

    def __init__(self, owner: SocketIO, conn: socket.socket, timeout: float | None) -> None:
        self._owner = owner
        self._conn = conn
        self._timeout = timeout
        self.io_thread = owner.thread

    def settimeout(self, timeout: float | None) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._timeout = timeout

    def gettimeout(self) -> float | None:
        return self._timeout

    def recv(self, size: int) -> bytes:
        return self._owner.call(self._conn, "recv", size, self._timeout)

    def sendall(self, data: bytes) -> None:
        self._owner.call(self._conn, "sendall", memoryview(data), self._timeout)

    def close(self) -> None:
        self._owner.call(self._conn, "close", None, None)
