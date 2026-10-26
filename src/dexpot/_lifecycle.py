"""Opt-in process lifecycle control plane, separate from connection execution."""

from __future__ import annotations

import contextlib
import os
import queue
import signal
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from .app import (
    _FT_OWNERS,
    _FT_OWNERS_LOCK,
    MAX_CONNECTIONS,
    SOCKET_BACKLOG,
    Dex,
    _logger,
    _multiprocessing,
    _reap_ft_owners,
)


class LifecycleRunner:
    def __init__(self, app: Dex) -> None:
        self._app = app
        self._lifecycle_factories: list[Callable[[], Any]] = []
        self._lifecycle_frozen = False
        self._deferred_lifecycle_stacks: list[contextlib.ExitStack] = []
        self._finalizer: threading.Thread | None = None
        self.cleanup_errors: list[BaseException] = []

    def __getattr__(self, name: str) -> Any:
        # Delegation is for startup/drain only. Connection owners bind to app.
        return getattr(self._app, name)

    def serve(self, host: str, port: int) -> None:
        with self._lifecycle_signals():
            self._serve(host, port)

    def _ensure_finalizer(self) -> None:
        # Caller holds the condition protecting active connections.
        if self._finalizer is not None:
            return
        worker = threading.Thread(
            target=self._finalize_when_idle, name="dexpot-lifecycle-finalizer", daemon=True
        )
        self._finalizer = worker
        try:
            worker.start()
        except BaseException:
            self._finalizer = None
            raise

    def _finalize_when_idle(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: not self._active_connections)
            try:
                self._release_deferred_lifecycle()
            except BaseException as exc:
                with self._cond:
                    self.cleanup_errors.append(exc)
                _logger.exception("Deferred lifecycle cleanup failed")
            with self._cond:
                if not self._deferred_lifecycle_stacks:
                    self._finalizer = None
                    return

    @contextlib.contextmanager
    def _acquire_lifecycle(self):
        with self._declaration_lock:
            self._lifecycle_frozen = True
            factories = tuple(self._lifecycle_factories)
        with contextlib.ExitStack() as stack:
            for factory in factories:
                manager = factory()
                if not hasattr(manager, "__enter__") or not hasattr(manager, "__exit__"):
                    raise TypeError("lifespan factory must return a synchronous context manager")
                stack.enter_context(manager)
            try:
                yield
            finally:
                # Atomically publish ownership before final completion can observe it.
                with self._cond:
                    if self._active_connections:
                        self._deferred_lifecycle_stacks.append(stack.pop_all())
                        self._ensure_finalizer()

    def _release_deferred_lifecycle(self) -> None:
        with self._cond:
            if self._active_connections or not self._deferred_lifecycle_stacks:
                return
            stacks, self._deferred_lifecycle_stacks = self._deferred_lifecycle_stacks, []
            self._cond.notify_all()
        with contextlib.ExitStack() as cleanup:
            for stack in stacks:
                cleanup.callback(stack.close)

    @contextlib.contextmanager
    def _lifecycle_signals(self):
        """Keep startup interruption cooperative, including factory acquisition."""
        self._stopping.clear()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_args: self._stopping.set())
        try:
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    def _serve(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self._bind_runtime()
        self._compile()
        workers_env = os.environ.get("DEXPOT_WORKERS", "")
        n_workers = max(1, int(workers_env)) if workers_env.isdigit() else 0

        if not self._serving_gil_free and n_workers > 1:
            self._serve_multiprocess(host, port, n_workers)
            return

        with self._acquire_lifecycle():
            if not self._stopping.is_set():
                self._serve_single_process(host, port)

    def _serve_single_process(self, host: str, port: int) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(SOCKET_BACKLOG)
            srv.settimeout(0.5)
            mode = (
                f"bounded-ft({MAX_CONNECTIONS})"
                if self._serving_gil_free
                else f"pooled-gil({self._pool_size})"
            )
            print(
                f"dexpot serving on http://{host}:{port} pid={os.getpid()} mode={mode} runtime={self._runtime_description()}",
                flush=True,
            )
            if not self._serving_gil_free:
                self._start_gil_workers(srv)
            stopping = self._stopping
            while not stopping.is_set():
                try:
                    conn, _addr = srv.accept()
                except TimeoutError:
                    self._check_runtime_mode()
                    continue
                self._check_runtime_mode()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.settimeout(self.limits.idle_read_seconds)
                self._handle_admission(conn, b"")
        finally:
            with contextlib.suppress(OSError):
                srv.close()
            self._begin_drain(timeout=5.0)

    def _begin_drain(self, timeout: float) -> None:
        """Stop new work and wait up to *timeout* for active connections.

        On deadline, leave in-flight connections and their application resources
        untouched; the serving caller may return while handlers finish.
        """
        self._stopping.set()
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._work:
                conn, _buf = self._work.popleft()
                with contextlib.suppress(OSError):
                    conn.close()
            self._cond.notify_all()
            while self._active_connections and time.monotonic() < deadline:
                self._cond.wait(timeout=min(0.1, max(0.0, deadline - time.monotonic())))
            survivors = list(self._active_connections) if not self._lifecycle_factories else []
        for conn in survivors:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
        with _FT_OWNERS_LOCK:
            owners = [owner for owner, (app, _slots) in _FT_OWNERS.items() if app is self._app]
        for owner in owners:
            if owner.ident is not None:
                owner.join(timeout=max(0.0, deadline - time.monotonic()))
        with _FT_OWNERS_LOCK:
            _reap_ft_owners()

    def _serve_multiprocess(self, host: str, port: int, n_workers: int) -> None:
        """Supervise one process-local SO_REUSEPORT listener per GIL worker."""
        if os.name != "posix":
            raise OSError(
                "DEXPOT_WORKERS > 1 requires POSIX fork + SO_REUSEPORT; "
                f"found {os.name!r}. Use DEXPOT_WORKERS=1 on this platform."
            )
        if not hasattr(socket, "SO_REUSEPORT"):
            raise OSError(
                "DEXPOT_WORKERS > 1 requires SO_REUSEPORT; use DEXPOT_WORKERS=1 on this platform."
            )
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError(
                "multiprocess serve() must run in the main thread; "
                "start dexpot from its CLI or a process, not a background thread"
            )

        # Preflight bind before launching anything. Workers create their own
        # process-local listeners after fork, so no child inherits unused peers.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            probe.bind((host, port))
        finally:
            probe.close()

        procs: list[Any] = []
        ready_channels: list[Any] = []
        stopping = self._stopping

        try:
            for _ in range(n_workers):
                if stopping.is_set():
                    return
                channel = _multiprocessing.Queue()
                proc = self._new_worker(host, port, channel)
                procs.append(proc)
                ready_channels.append(channel)
                procs[-1] = self._start_ready_worker(
                    self,
                    proc,
                    channel,
                    host,
                    port,
                    on_started=lambda started: procs.__setitem__(-1, started),
                )

            if stopping.is_set():
                return
            print(
                f"dexpot serving on http://{host}:{port} pid={os.getpid()} "
                f"mode=pooled-gil({self._pool_size})x{n_workers} runtime={self._runtime_description()}",
                flush=True,
            )
            while not stopping.is_set():
                self._restart_dead_workers(self, host, port, procs, ready_channels)
                stopping.wait(1.0)
        finally:
            self._teardown(procs)

    def _new_worker(self, host: str, port: int, ready: Any = None) -> Any:
        return _multiprocessing.Process(
            target=self._worker_process,
            args=(host, port, ready),
            daemon=True,
        )

    @staticmethod
    def _start_ready_worker(
        owner: LifecycleRunner,
        proc: Any,
        channel: Any,
        host: str,
        port: int,
        on_started: Callable[[Any], None] | None = None,
    ) -> Any:
        """Start a worker and wait for acquisition/listener readiness.

        Listener bind errors retain the bounded retry; application acquisition
        errors are fatal and never trigger repeated factory calls.
        """
        deadline = time.monotonic() + 3.0
        while True:
            if owner._stopping.is_set():
                return proc
            proc.start()
            if on_started is not None:
                on_started(proc)
            while True:
                if owner._stopping.is_set():
                    return proc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("dexpot worker did not acknowledge readiness")
                try:
                    status, detail = channel.get(timeout=min(0.05, remaining))
                    break
                except queue.Empty:
                    continue
                except Exception as exc:
                    if owner._stopping.is_set():
                        return proc
                    raise RuntimeError("dexpot worker did not acknowledge readiness") from exc
            if status == "stopped":
                owner._stopping.set()
                return proc
            if status == "ready":
                return proc
            proc.join(timeout=0.2)
            if status != "bind_error":
                raise RuntimeError(f"dexpot worker initialization failed: {detail}")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"dexpot worker listener bind failed: {detail}")
            if owner._stopping.wait(0.05):
                return proc
            proc = owner._new_worker(host, port, channel)

    @staticmethod
    def _restart_dead_workers(
        owner: LifecycleRunner, host: str, port: int, procs: list[Any], channels: list[Any]
    ) -> None:
        for i, proc in enumerate(procs):
            if owner._stopping.is_set():
                return
            if not proc.is_alive():
                print(f"dexpot worker {i} exited; restarting", flush=True)
                channel = _multiprocessing.Queue()
                replacement = owner._new_worker(host, port, channel)
                procs[i] = replacement
                channels[i] = channel
                procs[i] = owner._start_ready_worker(
                    owner,
                    replacement,
                    channel,
                    host,
                    port,
                    on_started=lambda started, index=i: procs.__setitem__(index, started),
                )

    @staticmethod
    def _teardown(procs: list[Any]) -> None:
        """Ask workers to stop accepting and drain active work for five seconds;
        kill only workers that exceed the deadline."""
        deadline = time.monotonic() + 6.0  # worker drain is 5s + IPC margin
        for proc in procs:
            with contextlib.suppress(Exception):
                proc.terminate()  # SIGTERM: worker handler initiates cooperative drain
        for proc in procs:
            remaining = max(0.0, deadline - time.monotonic())
            with contextlib.suppress(Exception):
                proc.join(timeout=remaining)
        for proc in procs:
            with contextlib.suppress(Exception):
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=1)

    def _worker_process(self, host: str, port: int, ready: Any = None) -> None:
        """Child entrypoint: acquire resources, acknowledge readiness, then drain."""
        try:
            stopped_before_listening = False
            with self._lifecycle_signals(), self._acquire_lifecycle():
                if self._stopping.is_set():
                    stopped_before_listening = True
                else:
                    self._worker_process_serving(host, port, ready)
            if stopped_before_listening and ready is not None:
                # Report cancellation only after acquisition has unwound. It is
                # neither successful readiness nor a retryable bind failure.
                ready.put(("stopped", ""))
        except BaseException as exc:
            if ready is not None:
                with contextlib.suppress(Exception):
                    ready.put(("fatal", f"{type(exc).__name__}: {exc}"))
            raise
        finally:
            # Only the parent enforces the forced process-exit deadline.
            worker = self._finalizer
            if worker is not None:
                worker.join()

    def _worker_process_serving(self, host: str, port: int, ready: Any = None) -> None:
        self._bind_runtime()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            try:
                listener.bind((host, port))
                listener.listen(SOCKET_BACKLOG)
            except OSError as exc:
                if ready is not None:
                    ready.put(("bind_error", str(exc)))
                return
            listener.settimeout(0.5)

            def stop(*_args: object) -> None:
                self._stopping.set()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)

            self._start_gil_workers(listener)
            if ready is not None:
                ready.put(("ready", ""))
            while not self._stopping.is_set():
                try:
                    conn, _addr = listener.accept()
                except TimeoutError:
                    self._check_runtime_mode()
                    continue
                self._check_runtime_mode()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.settimeout(self.limits.idle_read_seconds)
                self._handle_admission(conn, b"")
        finally:
            with contextlib.suppress(OSError):
                listener.close()
            self._begin_drain(timeout=5.0)
