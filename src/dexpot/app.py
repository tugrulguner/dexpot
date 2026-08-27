"""The Dex application: routing, validation, and the serving loop.

Ported from the gilpot-bench spike (micro6) with the same measured architecture:
- connection-owning threads, no asyncio
- mode-adaptive scheduling (unbounded threads on free-threaded CPython,
  bounded pool + fast-shed on GIL builds)
- msgspec fused decode+validate for typed bodies
- single-write responses
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import msgspec

from ._http import ClientDisconnected, HttpLimits, HTTPParseError, read_request

# "fork" is safe here because dexpot forks workers before starting any threads
# (the supervisor process never starts pools/reactors). It preserves the
# application object in-memory, avoiding pickle of compiled routes/codecs.
_multiprocessing = (
    multiprocessing.get_context("fork")
    if os.name == "posix"
    else multiprocessing.get_context("spawn")
)

SOCKET_BACKLOG = 4096

_cores = os.cpu_count() or 4
_is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
_gil_free = not _is_gil_enabled() if _is_gil_enabled is not None else False
POOL_SIZE = int(os.environ.get("DEXPOT_POOL", "0")) or (_cores if _gil_free else _cores * 2 + 2)
MAX_QUEUE = int(os.environ.get("DEXPOT_MAX_QUEUE", str(POOL_SIZE * 2)))

STATUS_TEXT = {
    200: b"OK",
    201: b"Created",
    204: b"No Content",
    400: b"Bad Request",
    404: b"Not Found",
    405: b"Method Not Allowed",
    408: b"Request Timeout",
    413: b"Content Too Large",
    414: b"URI Too Long",
    422: b"Unprocessable Entity",
    431: b"Request Header Fields Too Large",
    500: b"Internal Server Error",
    503: b"Service Unavailable",
    505: b"HTTP Version Not Supported",
}

_json_encode = msgspec.json.encode
_logger = logging.getLogger("dexpot.error")

_type_hints_cache: dict[Any, dict[str, Any]] = {}


def _type_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    hints = _type_hints_cache.get(fn)
    if hints is None:
        import inspect
        import typing

        raw = {n: p.annotation for n, p in inspect.signature(fn).parameters.items()}
        # resolve string annotations (from __future__ import annotations)
        resolved: dict[str, Any] = {}
        globalns = getattr(fn, "__globals__", {})
        closure = fn.__closure__ or ()
        cell_names = fn.__code__.co_freevars
        cells = dict(zip(cell_names, (c.cell_contents for c in closure), strict=True))
        for n, ann in raw.items():
            if isinstance(ann, str):
                with contextlib.suppress(Exception):
                    ann = eval(ann, dict(typing.__dict__), {**globalns, **cells})
            resolved[n] = ann
        hints = resolved
        _type_hints_cache[fn] = hints
    return hints


class HTTPError(Exception):
    """Raise from a handler to return an error status with a JSON detail."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


class Route:
    """Compiled, immutable endpoint plan. Built once at registration.

    The binder preserves Python signature semantics: each handler parameter
    resolves to a source (path capture by name, body, or default) regardless
    of the order path segments appear in or where the body parameter sits.
    """

    __slots__ = (
        "bind",
        "body_decoder",
        "body_type",
        "handler",
        "int_captures",
        "path_names",
        "resp_encoder",
        "resp_type",
        "summary",
    )

    def __init__(
        self,
        handler: Callable[..., Any],
        body_type: Any,
        resp_type: Any,
        summary: str,
        path_names: list[str],
    ) -> None:
        self.handler = handler
        self.body_type = body_type
        self.resp_type = resp_type
        self.summary = summary
        self.path_names = path_names
        self.body_decoder = msgspec.json.Decoder(body_type) if body_type is not None else None
        self.resp_encoder = msgspec.json.Encoder() if resp_type is not None else None

        # --- compile the binder in signature order ---
        hints = _type_hints(handler)
        sig = inspect.signature(handler)
        captures_by_name = {n: i for i, n in enumerate(path_names)}

        sources: list[tuple[Any, str, str, Any]] = []
        int_captures: list[tuple[int, str]] = []  # (capture_index, param_name)
        used_captures: set[int] = set()
        body_param_seen = False

        for name, param in sig.parameters.items():
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"handler parameter '{name}' uses unsupported "
                    f"{param.kind.description}; *args/**kwargs cannot be compiled"
                )

            ann = hints.get(name)
            if name in captures_by_name:
                idx = captures_by_name[name]
                if ann is int:
                    int_captures.append((idx, name))
                sources.append((param.kind, name, "capture", idx))
                used_captures.add(idx)
            elif body_type is not None and not body_param_seen:
                body_param_seen = True
                sources.append((param.kind, name, "body", None))
            elif param.default is not inspect.Parameter.empty:
                sources.append((param.kind, name, "default", param.default))
            else:
                raise TypeError(
                    f"handler parameter '{name}' on route "
                    f"cannot be bound: no matching path segment, body, or default"
                )

        self.int_captures = tuple(int_captures)

        # Build positional and keyword-only invokers in signature order.
        # Common routes allocate no kwargs dict; keyword-only routes do.
        positional_sources = [
            (source, payload)
            for kind, _name, source, payload in sources
            if kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        keyword_sources = [
            (name, source, payload)
            for kind, name, source, payload in sources
            if kind is inspect.Parameter.KEYWORD_ONLY
        ]

        def resolve(source: str, payload: Any, captures: list[Any], body: Any) -> Any:
            if source == "capture":
                return captures[payload]
            if source == "body":
                return body
            return payload

        def bind(captures: list[Any], body: Any) -> tuple[list[Any], dict[str, Any] | None]:
            args = [
                resolve(source, payload, captures, body) for source, payload in positional_sources
            ]
            kwargs = (
                {
                    name: resolve(source, payload, captures, body)
                    for name, source, payload in keyword_sources
                }
                if keyword_sources
                else None
            )
            return args, kwargs

        self.bind = bind  # type: ignore[assignment]

        # every path segment must be consumed by a handler parameter
        unconsumed = [path_names[i] for i in range(len(path_names)) if i not in used_captures]
        if unconsumed:
            raise TypeError(f"path parameter(s) {unconsumed} are not accepted by the handler")

    def encode(self, result: Any) -> bytes:
        """Encode a successful result using the route's response contract."""
        if self.resp_encoder is not None and type(result) is self.resp_type:
            return self.resp_encoder.encode(result)
        return _json_encode(result)


def _path_segments(path: str) -> list[str]:
    if path == "/":
        return []
    return path[1:].split("/")


class Dex:
    """The application. ``@dex.get(...)`` / ``@dex.post(...)`` register routes."""

    def __init__(self, *, limits: HttpLimits | None = None) -> None:
        self.limits = limits or HttpLimits()
        self._literal: dict[tuple[str, str], Route] = {}
        self._parametric: list[tuple[str, list[str], Route]] = []
        self._work: deque[tuple[socket.socket, bytes]] = deque()
        self._cond = threading.Condition()
        self._stopping = threading.Event()
        self._active_connections: set[socket.socket] = set()

    # ---- route registration ----

    def _register(self, method: str, path: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("route paths must be absolute paths without a query or fragment")
        body_type = getattr(fn, "__dexpot_body__", None)
        resp_type = getattr(fn, "__dexpot_resp__", None)
        path_names = [
            s[1:-1] for s in _path_segments(path) if s.startswith("{") and s.endswith("}")
        ]
        route = Route(fn, body_type, resp_type, (fn.__doc__ or "").strip(), path_names)
        key = (method, path)
        if "{" in path:
            # structural shape: literal segments kept, params normalized to {},
            # so /users/{id} and /users/{name} are correctly seen as duplicates
            shape = tuple(
                "{}" if s.startswith("{") and s.endswith("}") else s for s in _path_segments(path)
            )
            for m, _p, _r in self._parametric:
                existing_shape = tuple(
                    "{}" if seg.startswith("{") and seg.endswith("}") else seg for seg in _p
                )
                if m == method and existing_shape == shape:
                    raise ValueError(f"duplicate route: {method} {path}")
            segments = _path_segments(path)
            self._parametric.append((method, segments, route))
        else:
            if key in self._literal:
                raise ValueError(f"duplicate route: {method} {path}")
            self._literal[key] = route
        return fn

    def get(
        self, path: str, response: Any = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("GET", path, None, response)

    def post(
        self, path: str, body: Any = None, response: Any = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("POST", path, body, response)

    def put(
        self, path: str, body: Any = None, response: Any = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("PUT", path, body, response)

    def patch(
        self, path: str, body: Any = None, response: Any = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("PATCH", path, body, response)

    def delete(
        self, path: str, response: Any = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("DELETE", path, None, response)

    def _method_decorator(
        self, method: str, path: str, body: Any, response: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            body_type = body
            if body_type is None:
                # fall back to live annotation object if present (no __future__ import)
                hints = {n: p.annotation for n, p in inspect.signature(fn).parameters.items()}
                for ann in hints.values():
                    if isinstance(ann, type) and issubclass(ann, msgspec.Struct):
                        body_type = ann
                        break
            if body_type is not None:
                fn.__dexpot_body__ = body_type  # type: ignore[attr-defined]
            if response is not None:
                fn.__dexpot_resp__ = response  # type: ignore[attr-defined]
            return self._register(method, path, fn)

        return deco

    # ---- matching ----

    def _match(
        self, method: str, path: str
    ) -> tuple[Route | None, list[Any] | None, tuple[str, ...]]:
        hit = self._literal.get((method, path))
        if hit is not None:
            return hit, [], ()
        allowed = {
            registered_method
            for registered_method, registered_path in self._literal
            if registered_path == path
        }
        segs = _path_segments(path)
        for registered_method, pattern, route in self._parametric:
            if len(pattern) != len(segs):
                continue
            captures: list[Any] = []
            ok = True
            for expected, actual in zip(pattern, segs, strict=True):
                if expected.startswith("{") and expected.endswith("}"):
                    captures.append(actual)
                elif expected != actual:
                    ok = False
                    break
            if ok:
                if registered_method == method:
                    return route, captures, ()
                allowed.add(registered_method)
        return None, None, tuple(sorted(allowed))

    # ---- request processing ----

    def _process(self, conn: socket.socket, buf: bytes) -> tuple[bool, bytes]:
        try:
            request, buf = read_request(conn, buf, self.limits)
        except ClientDisconnected:
            return False, b""
        except HTTPParseError as exc:
            self._send(
                conn,
                exc.status,
                _json_encode({"detail": exc.detail}),
                keep_alive=False,
                version=exc.version or "HTTP/1.1",
            )
            return False, b""

        route, captures_list, allowed = self._match(request.method, request.path)
        if route is None or captures_list is None:
            if allowed:
                self._send(
                    conn,
                    405,
                    _json_encode({"detail": "method not allowed"}),
                    keep_alive=request.keep_alive,
                    version=request.version,
                    extra_headers=(("Allow", ", ".join(allowed)),),
                )
            else:
                self._send(
                    conn,
                    404,
                    _json_encode({"detail": "not found"}),
                    keep_alive=request.keep_alive,
                    version=request.version,
                )
            return request.keep_alive, buf

        try:
            # compiled binder: convert typed captures, then build args in
            # signature order (path by name, body, defaults)
            for cap_idx, pname in route.int_captures:
                try:
                    captures_list[cap_idx] = int(captures_list[cap_idx])
                except ValueError:
                    self._send(
                        conn,
                        422,
                        _json_encode({"detail": f"invalid int for {pname}"}),
                        keep_alive=request.keep_alive,
                        version=request.version,
                    )
                    return request.keep_alive, buf

            body_arg: Any = None
            if route.body_decoder is not None:
                try:
                    body_arg = route.body_decoder.decode(request.body)
                except (msgspec.ValidationError, msgspec.DecodeError) as exc:
                    self._send(
                        conn,
                        422,
                        _json_encode({"detail": str(exc)}),
                        keep_alive=request.keep_alive,
                        version=request.version,
                    )
                    return request.keep_alive, buf

            args, kwargs = route.bind(captures_list, body_arg)
            result = route.handler(*args, **kwargs) if kwargs else route.handler(*args)
            if isinstance(result, tuple):
                status, payload = result
                out = _json_encode(payload)
            else:
                status, out = 200, route.encode(result)
        except HTTPError as exc:
            status = exc.status
            out = _json_encode({"detail": exc.detail})
        except Exception:
            _logger.exception(
                "unhandled exception while processing %s %s", request.method, request.path
            )
            status = 500
            out = _json_encode({"detail": "internal server error"})
        self._send(
            conn,
            status,
            out,
            keep_alive=request.keep_alive,
            version=request.version,
        )
        return request.keep_alive, buf

    @staticmethod
    def _send(
        conn: socket.socket,
        status: int,
        out: bytes,
        *,
        keep_alive: bool,
        version: str = "HTTP/1.1",
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        reason = STATUS_TEXT.get(status, b"OK")
        header = (
            b"%s %d %s\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\nServer: dexpot\r\nConnection: %s\r\n"
            % (
                version.encode("ascii"),
                status,
                reason,
                len(out),
                b"keep-alive" if keep_alive else b"close",
            )
        )
        for name, value in extra_headers:
            header += f"{name}: {value}\r\n".encode("latin-1")
        conn.sendall(header + b"\r\n" + out)

    # ---- scheduling ----

    def _worker_gil(self) -> None:
        cond = self._cond
        while True:
            with cond:
                while not self._work and not self._stopping.is_set():
                    cond.wait(timeout=0.5)
                if self._stopping.is_set() and not self._work:
                    return
                conn, buf = self._work.popleft()
                self._active_connections.add(conn)
            try:
                while not self._stopping.is_set():
                    keep_alive, buf = self._process(conn, buf)
                    if not keep_alive:
                        break
                conn.close()
            except (ConnectionError, OSError, ValueError):
                with contextlib.suppress(OSError):
                    conn.close()
            finally:
                with cond:
                    self._active_connections.discard(conn)
                    cond.notify_all()

    def _own_connection(self, conn: socket.socket, buf: bytes) -> None:
        with self._cond:
            self._active_connections.add(conn)
        try:
            while not self._stopping.is_set():
                keep_alive, buf = self._process(conn, buf)
                if not keep_alive:
                    break
            conn.close()
        except (ConnectionError, OSError, ValueError):
            with contextlib.suppress(OSError):
                conn.close()
        finally:
            with self._cond:
                self._active_connections.discard(conn)
                self._cond.notify_all()

    def _handle_admission(self, conn: socket.socket, buf: bytes) -> None:
        if self._stopping.is_set():
            with contextlib.suppress(OSError):
                conn.close()
            return
        if _gil_free:
            # free-threaded: threads are cheap and truly parallel — spawn per connection.
            threading.Thread(target=self._own_connection, args=(conn, buf), daemon=True).start()
            return
        # GIL build: bounded pool + fast-shed on saturation.
        with self._cond:
            saturated = len(self._work) >= MAX_QUEUE
            if not saturated:
                self._work.append((conn, buf))
                self._cond.notify()
        if saturated:
            try:
                out = _json_encode({"detail": "overloaded"})
                conn.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                    b"Content-Length: %d\r\nRetry-After: 1\r\nConnection: close\r\n\r\n%s"
                    % (len(out), out)
                )
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    conn.close()

    # ---- serving ----

    def _make_listener(self, host: str, reuseport: bool) -> socket.socket:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if reuseport and hasattr(socket, "SO_REUSEPORT"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        return srv

    def serve(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        workers_env = os.environ.get("DEXPOT_WORKERS", "")
        n_workers = max(1, int(workers_env)) if workers_env.isdigit() else 0

        if not _gil_free and n_workers > 1:
            self._serve_multiprocess(host, port, n_workers)
            return

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(SOCKET_BACKLOG)
        srv.settimeout(0.5)
        mode = "unbounded-ft" if _gil_free else f"pooled-gil({POOL_SIZE})"
        print(f"dexpot serving on http://{host}:{port} pid={os.getpid()} mode={mode}", flush=True)
        if not _gil_free:
            for _ in range(POOL_SIZE):
                threading.Thread(target=self._worker_gil, daemon=True).start()
        # clean exit on SIGTERM/SIGINT (main thread only); otherwise default behavior
        stopping = threading.Event()

        def stop(*_args: object) -> None:
            stopping.set()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
        while not stopping.is_set():
            try:
                conn, _addr = srv.accept()
            except TimeoutError:
                continue
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(self.limits.idle_read_seconds)
            self._handle_admission(conn, b"")
        with contextlib.suppress(OSError):
            srv.close()
        self._begin_drain(timeout=5.0)

    def _begin_drain(self, timeout: float) -> None:
        """Stop new work, discard queued idle connections, and wait for active
        connections up to *timeout*. Close survivors after the deadline."""
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
            survivors = list(self._active_connections)
        for conn in survivors:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()

    def _accept_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _addr = srv.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(self.limits.idle_read_seconds)
            self._handle_admission(conn, b"")

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

        print(
            f"dexpot serving on http://{host}:{port} pid={os.getpid()} "
            f"mode=pooled-gil({POOL_SIZE})x{n_workers}",
            flush=True,
        )

        procs: list[Any] = []
        stopping = threading.Event()

        def stop(*_args: object) -> None:
            stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        try:
            for _ in range(n_workers):
                proc = self._new_worker(host, port)
                proc.start()
                procs.append(proc)

            # Stabilize the full worker set before announcing startup success.
            # On macOS, rapid SO_REUSEPORT restarts can transiently fail one
            # child bind; retry within a bounded startup window. If the set
            # cannot stabilize, teardown is atomic in the finally block.
            startup_deadline = time.monotonic() + 3.0
            while True:
                dead = [i for i, p in enumerate(procs) if not p.is_alive()]
                if not dead:
                    break
                if time.monotonic() >= startup_deadline:
                    raise RuntimeError(f"{len(dead)} dexpot worker(s) failed during startup")
                for i in dead:
                    replacement = self._new_worker(host, port)
                    replacement.start()
                    procs[i] = replacement
                time.sleep(0.2)

            while not stopping.is_set():
                self._restart_dead_workers(self, host, port, procs)
                stopping.wait(1.0)
        finally:
            self._teardown(procs)

    def _new_worker(self, host: str, port: int) -> Any:
        return _multiprocessing.Process(
            target=self._worker_process,
            args=(host, port),
            daemon=True,
        )

    @staticmethod
    def _restart_dead_workers(owner: Dex, host: str, port: int, procs: list[Any]) -> None:
        for i, proc in enumerate(procs):
            if not proc.is_alive():
                print(f"dexpot worker {i} exited; restarting", flush=True)
                replacement = owner._new_worker(host, port)
                replacement.start()
                procs[i] = replacement

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

    def _worker_process(self, host: str, port: int) -> None:
        """Child entrypoint: create a process-local listener, serve, then drain."""
        self._stopping.clear()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        listener.bind((host, port))
        listener.listen(SOCKET_BACKLOG)
        listener.settimeout(0.5)

        def stop(*_args: object) -> None:
            self._stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        for _ in range(POOL_SIZE):
            threading.Thread(target=self._worker_gil, daemon=True).start()

        try:
            while not self._stopping.is_set():
                try:
                    conn, _addr = listener.accept()
                except TimeoutError:
                    continue
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.settimeout(self.limits.idle_read_seconds)
                self._handle_admission(conn, b"")
        finally:
            with contextlib.suppress(OSError):
                listener.close()
            self._begin_drain(timeout=5.0)
