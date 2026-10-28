"""Bounded readiness-owned socket I/O for a synchronous GIL handler pool."""

from __future__ import annotations

import contextlib
import errno
import queue
import selectors
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Prefetch:
    conn: socket.socket
    fd: int
    condition: threading.Condition = field(default_factory=threading.Condition)
    data: bytearray = field(default_factory=bytearray)
    available_at: float = 0
    ended_at: float = 0
    eof: bool = False
    closed: bool = False
    error: BaseException | None = None
    limit: int = 65536
    outgoing: _Call | None = None
    wake_on_write: bool = False
    read_budget: float | None = None


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
    finished_at: float = 0
    pipeline: bool = False


class SocketIO:
    """One process-local owner; persistent bounded reads and synchronous writes."""

    def __init__(self) -> None:
        self._commands: queue.SimpleQueue[_Call] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._wake_pending = False
        self._awake_coalescing = sys.platform == "darwin"
        self._sleeping = False
        self._stopping = False
        self._connections: set[socket.socket] = set()
        self._states: dict[socket.socket, _Prefetch] = {}
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
        state = _Prefetch(conn, conn.fileno())
        with self._lock:
            if self._stopping:
                raise OSError(errno.EBADF, "I/O owner is closed")
            if conn in self._states:
                raise RuntimeError("connection already owned")
            conn.setblocking(False)
            self._connections.add(conn)
            self._states[conn] = state
        self.call(conn, "register", None, None)
        return SocketOwner(self, state, timeout)

    def _wake(self) -> None:
        with contextlib.suppress(OSError):
            self._writer.send(b"\0")

    def _submit(
        self, conn: socket.socket, operation: str, argument: Any, timeout: float | None
    ) -> _Call:
        task = _Call(
            conn,
            operation,
            argument,
            time.monotonic() + timeout if timeout is not None else None,
            timeout == 0,
        )
        self._enqueue(task)
        return task

    def _enqueue(self, task: _Call) -> None:
        with self._lock:
            if self._stopping:
                raise OSError(errno.EBADF, "I/O owner is closed")
            self._commands.put(task)
            wake = not self._wake_pending and (not self._awake_coalescing or self._sleeping)
            if wake:
                self._wake_pending = True
        if wake:
            self._wake()

    def call(
        self, conn: socket.socket, operation: str, argument: Any, timeout: float | None
    ) -> Any:
        try:
            task = self._submit(conn, operation, argument, timeout)
        except OSError:
            if operation == "close":
                conn.close()
                return None
            raise
        task.done.wait()
        if task.error is not None:
            raise task.error
        return task.value

    def _state(self, conn: socket.socket) -> _Prefetch:
        with self._lock:
            state = self._states.get(conn)
        if state is None:
            raise OSError(errno.EBADF, "socket is no longer owned")
        return state

    def _unregister(self, state: _Prefetch) -> None:
        with contextlib.suppress(KeyError, ValueError, OSError):
            if self._selector.get_key(state.fd).data is state:
                self._selector.unregister(state.fd)

    def _mark_closed(self, state: _Prefetch, error: BaseException) -> None:
        self._unregister(state)
        with state.condition:
            state.closed = True
            state.error = error
            state.condition.notify_all()
        pending = self._pending.get(state.conn)
        if pending is not None:
            self._finish(pending, error=error)

    def _set_events(self, state: _Prefetch) -> None:
        with state.condition:
            readable = (
                not (state.closed or state.eof or state.error) and len(state.data) < state.limit
            )
            closed = state.closed
        events = (selectors.EVENT_READ if readable else 0) | (
            selectors.EVENT_WRITE if state.conn in self._pending and not closed else 0
        )
        if state.conn.fileno() != state.fd:
            self._mark_closed(state, OSError(errno.EBADF, "socket closed"))
            return
        try:
            key = self._selector.get_key(state.fd)
        except KeyError:
            key = None
        if key is not None and key.data is not state:
            previous = key.data
            if isinstance(previous, _Prefetch) and previous.conn.fileno() != previous.fd:
                self._mark_closed(previous, OSError(errno.EBADF, "socket closed"))
                key = None
            else:
                raise OSError(errno.EBUSY, "descriptor already owned")
        if not events:
            self._unregister(state)
        elif key is None:
            self._selector.register(state.conn, events, state)
        elif key.events != events:
            self._selector.modify(state.fd, events, state)

    def _finish(self, task: _Call, value: Any = None, error: BaseException | None = None) -> None:
        if self._pending.get(task.conn) is task:
            del self._pending[task.conn]
            try:
                self._set_events(self._state(task.conn))
            except (OSError, ValueError) as exc:
                if error is None:
                    error = exc
        task.value, task.error = value, error
        if task.pipeline:
            task.finished_at = time.monotonic()
        task.done.set()
        if not task.pipeline:
            return
        try:
            state = self._state(task.conn)
        except OSError:
            return
        with state.condition:
            if state.outgoing is task and (
                state.data
                or state.eof
                or state.error
                or state.closed
                or state.wake_on_write
                or error is not None
                or task.deadline is None
                or (
                    state.read_budget is not None
                    and task.deadline > task.finished_at + state.read_budget
                )
            ):
                state.condition.notify_all()

    def _advance(self, task: _Call) -> None:
        if task.done.is_set():
            return
        state = None
        try:
            state = self._state(task.conn)
            if task.operation == "close":
                self._mark_closed(state, OSError(errno.EBADF, "socket closed"))
                try:
                    task.conn.close()
                finally:
                    if task.conn.fileno() < 0:
                        with self._lock:
                            self._connections.discard(task.conn)
                            self._states.pop(task.conn, None)
                self._finish(task)
                return
            if task.operation in ("register", "resume"):
                self._set_events(state)
                self._finish(task)
                return
            if task.operation != "sendall":
                raise ValueError("unsupported I/O operation")
            if (
                task.deadline is not None
                and not task.nonblocking
                and time.monotonic() >= task.deadline
            ):
                raise TimeoutError("timed out")
            if state.closed or task.conn.fileno() != state.fd:
                raise OSError(errno.EBADF, "socket closed")
            previous = self._pending.get(task.conn)
            if previous is not None and previous is not task:
                raise RuntimeError("overlapping writes on one connection")
            data = task.argument
            if task.offset < len(data):
                try:
                    sent = task.conn.send(data[task.offset :])
                    if sent == 0:
                        raise ConnectionResetError("socket write returned zero")
                    task.offset += sent
                except BlockingIOError:
                    pass
            if task.offset == len(data):
                self._finish(task)
            elif task.nonblocking:
                raise BlockingIOError(errno.EWOULDBLOCK, "operation would block")
            else:
                self._pending[task.conn] = task
                self._set_events(state)
        except BaseException as exc:
            if state is not None and task.operation in ("register", "resume"):
                self._mark_closed(state, exc)
            self._finish(task, error=exc)

    def _drain_commands(self) -> None:
        with self._lock:
            turn_size = self._commands.qsize()
            self._wake_pending = False
        for _ in range(turn_size):
            with self._lock:
                try:
                    task = self._commands.get_nowait()
                except queue.Empty:
                    return
            self._advance(task)

    def _read_ready(self, state: _Prefetch) -> None:
        with state.condition:
            capacity = state.limit - len(state.data)
            if state.closed or state.eof or state.error or capacity <= 0:
                return
        try:
            data = state.conn.recv(capacity)
        except BlockingIOError:
            return
        except OSError as exc:
            observed = time.monotonic()
            with state.condition:
                state.error = exc
                state.ended_at = observed
                state.condition.notify_all()
        else:
            observed = time.monotonic()
            with state.condition:
                if data:
                    if not state.data:
                        state.available_at = observed
                    state.data.extend(data)
                else:
                    state.eof = True
                    state.ended_at = observed
                state.condition.notify_all()
        self._set_events(state)

    def _poll(self, timeout: float) -> Any:
        if not self._awake_coalescing:
            return self._selector.select(timeout)
        with self._lock:
            if self._commands.empty():
                self._sleeping = True
            else:
                timeout = 0
        try:
            return self._selector.select(timeout)
        finally:
            with self._lock:
                self._sleeping = False

    def _run(self) -> None:
        try:
            while True:
                self._drain_commands()
                with self._lock:
                    if self._stopping:
                        return
                    states = list(self._states.values())
                for state in states:
                    if state.conn.fileno() != state.fd:
                        self._mark_closed(state, OSError(errno.EBADF, "socket closed"))
                        if state.conn.fileno() < 0:
                            with self._lock:
                                self._states.pop(state.conn, None)
                                self._connections.discard(state.conn)
                now = time.monotonic()
                for task in list(self._pending.values()):
                    if task.deadline is not None and now >= task.deadline:
                        self._finish(task, error=TimeoutError("timed out"))
                deadlines = [
                    task.deadline for task in self._pending.values() if task.deadline is not None
                ]
                timeout = min(0.5, max(0, min(deadlines) - time.monotonic())) if deadlines else 0.5
                for key, events in self._poll(timeout):
                    if key.data is None:
                        while True:
                            try:
                                if not self._reader.recv(4096):
                                    break
                            except BlockingIOError:
                                break
                    else:
                        state = key.data
                        if state.closed or state.conn.fileno() != state.fd:
                            self._mark_closed(state, OSError(errno.EBADF, "socket closed"))
                            continue
                        if events & selectors.EVENT_READ:
                            self._read_ready(state)
                        task = self._pending.get(state.conn)
                        if events & selectors.EVENT_WRITE and task is not None:
                            self._advance(task)
        finally:
            with self._lock:
                self._stopping = True
                states = list(self._states.values())
                connections = list(self._connections)
            for state in states:
                self._mark_closed(state, OSError(errno.EBADF, "I/O owner stopped"))
            while True:
                try:
                    task = self._commands.get_nowait()
                except queue.Empty:
                    break
                self._finish(task, error=OSError(errno.EBADF, "I/O owner stopped"))
            for conn in connections:
                with contextlib.suppress(OSError):
                    conn.close()
            with self._lock:
                self._states.clear()
                self._connections.clear()
            self._selector.close()
            self._reader.close()
            self._writer.close()

    def close(self, timeout: float = 1) -> None:
        with self._lock:
            self._stopping = True
        self._wake()
        self.thread.join(timeout=max(0, timeout))


class SocketOwner:
    """Connection-pinned facade; receive waits on bounded owner-prefetched bytes."""

    def __init__(self, owner: SocketIO, state: _Prefetch, timeout: float | None) -> None:
        self._owner = owner
        self._state = state
        self._conn = state.conn
        self._timeout = timeout
        self.io_thread = owner.thread
        self.pipeline = False
        self._first_receive_deadline: float | None = None

    def settimeout(self, timeout: float | None) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._timeout = timeout

    def gettimeout(self) -> float | None:
        return self._timeout

    def recv(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("negative buffersize in recv")
        deadline = time.monotonic() + self._timeout if self._timeout is not None else None
        if size and self._first_receive_deadline is not None:
            deadline = (
                min(deadline, self._first_receive_deadline)
                if deadline is not None
                else self._first_receive_deadline
            )
            self._first_receive_deadline = None
        state = self._state
        with state.condition:
            while True:
                if state.closed:
                    if state.error is not None:
                        raise state.error
                    raise OSError(errno.EBADF, "socket closed")
                if size == 0:
                    return b""
                if state.data:
                    if (
                        self._timeout != 0
                        and deadline is not None
                        and state.available_at > deadline
                    ):
                        raise TimeoutError("timed out")
                    was_full = len(state.data) == state.limit
                    result = bytes(state.data[:size])
                    del state.data[:size]
                    if was_full:
                        self._owner._submit(self._conn, "resume", None, None)
                    return result
                if (
                    (state.error is not None or state.eof)
                    and self._timeout != 0
                    and deadline is not None
                    and state.ended_at > deadline
                ):
                    raise TimeoutError("timed out")
                if state.error is not None:
                    raise state.error
                if state.eof:
                    return b""
                if self._timeout == 0:
                    raise BlockingIOError(errno.EWOULDBLOCK, "operation would block")
                remaining = deadline - time.monotonic() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("timed out")
                state.condition.wait(remaining)

    def wait_request(
        self, head_seconds: float, idle_seconds: float, buffered: bool = False
    ) -> float:
        """Wait for commit plus first bytes; carry, rather than reset, read budgets."""
        started = time.monotonic()
        state = self._state
        with state.condition:
            state.wake_on_write = buffered
            state.read_budget = min(head_seconds, idle_seconds)
            try:
                while True:
                    if state.closed:
                        raise state.error or OSError(errno.EBADF, "socket closed")
                    pending = state.outgoing
                    now = time.monotonic()
                    if pending is not None and not pending.done.is_set():
                        remaining = pending.deadline - now if pending.deadline is not None else None
                        if remaining is not None and remaining <= 0:
                            raise TimeoutError("response write timed out")
                        state.condition.wait(remaining)
                        continue
                    if pending is not None and pending.error is not None:
                        raise pending.error
                    base = pending.finished_at if pending is not None else started
                    head_deadline = base + head_seconds
                    idle_deadline = base + idle_seconds
                    if (
                        buffered
                        or state.data
                        or state.eof
                        or state.error is not None
                        or now >= min(head_deadline, idle_deadline)
                    ):
                        self._first_receive_deadline = None if buffered else idle_deadline
                        return head_deadline
                    state.condition.wait(min(head_deadline, idle_deadline) - now)
            finally:
                state.wake_on_write = False
                state.read_budget = None

    def sendall(self, data: bytes) -> None:
        if not self.pipeline:
            self._owner.call(self._conn, "sendall", memoryview(data), self._timeout)
            return
        task = _Call(
            self._conn,
            "sendall",
            memoryview(data),
            time.monotonic() + self._timeout if self._timeout is not None else None,
            self._timeout == 0,
            pipeline=True,
        )
        with self._state.condition:
            if self._state.closed:
                raise OSError(errno.EBADF, "socket closed")
            previous = self._state.outgoing
            if previous is not None and not previous.done.is_set():
                raise RuntimeError("previous response has not completed")
            self._state.outgoing = task
        try:
            self._owner._enqueue(task)
        except BaseException as exc:
            task.error = exc
            task.finished_at = time.monotonic()
            task.done.set()
            with self._state.condition:
                self._state.condition.notify_all()
            raise

    def close(self) -> None:
        pending = self._state.outgoing
        try:
            if pending is not None:
                pending.done.wait()
                if pending.error is not None:
                    raise pending.error
        finally:
            self._owner.call(self._conn, "close", None, None)
