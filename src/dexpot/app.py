"""The Dex application: routing, validation, and the serving loop.

Ported from the gilpot-bench spike (micro6) with the same measured architecture:
- thread-per-request, no asyncio
- mode-adaptive scheduling (unbounded threads on free-threaded CPython,
  bounded pool + fast-shed on GIL builds)
- msgspec fused decode+validate for typed bodies
- single-write responses
"""

from __future__ import annotations

import contextlib
import inspect
import multiprocessing
import os
import signal
import socket
import sys
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

import msgspec

# "fork" is safe here because dexpot forks workers before starting any threads
# (the supervisor process never starts pools/reactors). It preserves the
# application object in-memory, avoiding pickle of compiled routes/codecs.
_multiprocessing = multiprocessing.get_context("fork") if os.name == "posix" else multiprocessing.get_context("spawn")

SOCKET_BACKLOG = 4096
RECV_SIZE = 65536

_cores = os.cpu_count() or 4
_is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
_gil_free = not _is_gil_enabled() if _is_gil_enabled is not None else False
POOL_SIZE = int(os.environ.get("DEXPOT_POOL", "0")) or (_cores if _gil_free else _cores * 2 + 2)
MAX_QUEUE = int(os.environ.get("DEXPOT_MAX_QUEUE", str(POOL_SIZE * 2)))

STATUS_TEXT = {
    200: b"OK",
    201: b"Created",
    204: b"No Content",
    404: b"Not Found",
    422: b"Unprocessable Entity",
    500: b"Internal Server Error",
    503: b"Service Unavailable",
}

_json_encode = msgspec.json.encode

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
    """Compiled, immutable endpoint plan. Built once at registration."""

    __slots__ = (
        "body_decoder",
        "body_type",
        "handler",
        "int_slots",
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
        hints = _type_hints(handler)
        # positional slots (in capture order) whose values must be converted to int
        self.int_slots = tuple(
            path_names.index(n) for n in path_names if hints.get(n) is int
        )

    def encode(self, result: Any) -> bytes:
        """Encode a successful result using the route's response contract."""
        if self.resp_encoder is not None and type(result) is self.resp_type:
            return self.resp_encoder.encode(result)
        return _json_encode(result)


class Dex:
    """The application. ``@dex.get(...)`` / ``@dex.post(...)`` register routes."""

    def __init__(self) -> None:
        self._literal: dict[tuple[str, str], Route] = {}
        self._parametric: list[tuple[str, list[str], Route]] = []
        self._work: deque[tuple[socket.socket, bytes]] = deque()
        self._cond = threading.Condition()

    # ---- route registration ----

    def _register(self, method: str, path: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        body_type = getattr(fn, "__dexpot_body__", None)
        resp_type = getattr(fn, "__dexpot_resp__", None)
        path_names = [s[1:-1] for s in path.strip("/").split("/") if s.startswith("{") and s.endswith("}")]
        route = Route(fn, body_type, resp_type, (fn.__doc__ or "").strip(), path_names)
        key = (method, path)
        if "{" in path:
            if any(m == method and p == path for m, p, _r in self._parametric):
                raise ValueError(f"duplicate route: {method} {path}")
            segments = path.strip("/").split("/")
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

    def _match(self, method: str, path: str) -> tuple[Route | None, list[Any] | None]:
        hit = self._literal.get((method, path))
        if hit is not None:
            return hit, []
        segs = path.strip("/").split("/")
        for m, pattern, route in self._parametric:
            if m != method or len(pattern) != len(segs):
                continue
            captures: list[Any] = []
            ok = True
            for p, s in zip(pattern, segs, strict=True):
                if p.startswith("{") and p.endswith("}"):
                    captures.append(s)
                elif p != s:
                    ok = False
                    break
            if ok:
                return route, captures
        return None, None

    # ---- request processing ----

    def _process(self, conn: socket.socket, buf: bytes) -> tuple[bool, bytes]:
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(RECV_SIZE)
            if not chunk:
                return False, b""
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        try:
            method, raw_path, _ver = lines[0].decode("latin-1").split(" ", 2)
        except ValueError:
            return False, b""
        content_length = 0
        keep_alive = True
        headers: dict[str, str] = {}
        for line in lines[1:]:
            k, _, v = line.partition(b":")
            key = k.strip().lower().decode("latin-1")
            val = v.strip()
            headers[key] = val.decode("latin-1")
            if key == "content-length":
                content_length = int(val)
            elif key == "connection" and val.lower() == b"close":
                keep_alive = False
        while len(rest) < content_length:
            chunk = conn.recv(RECV_SIZE)
            if not chunk:
                return False, b""
            rest += chunk
        body_bytes, buf = rest[:content_length], rest[content_length:]

        path_only, _, _query = raw_path.partition("?")
        route, captures_list = self._match(method, path_only)
        if route is None or captures_list is None:
            self._send(conn, 404, _json_encode({"detail": "not found"}))
            return keep_alive, buf

        try:
            # compiled positional layout: convert typed path slots in place
            captures = list(captures_list)
            for slot in route.int_slots:
                try:
                    captures[slot] = int(captures[slot])
                except ValueError:
                    name = route.path_names[slot] if slot < len(route.path_names) else str(slot)
                    self._send(conn, 422, _json_encode({"detail": f"invalid int for {name}"}))
                    return keep_alive, buf

            args: list[Any] = list(captures)
            if route.body_decoder is not None:
                try:
                    args.append(route.body_decoder.decode(body_bytes))
                except (msgspec.ValidationError, msgspec.DecodeError) as exc:
                    self._send(conn, 422, _json_encode({"detail": str(exc)}))
                    return keep_alive, buf

            result = route.handler(*args)
            if isinstance(result, tuple):
                status, payload = result
                out = _json_encode(payload)
            else:
                status, out = 200, route.encode(result)
        except HTTPError as exc:
            status = exc.status
            out = _json_encode({"detail": exc.detail})
        except Exception as exc:
            status = 500
            out = _json_encode({"detail": f"{type(exc).__name__}: {exc}"})
        self._send(conn, status, out)
        return keep_alive, buf

    @staticmethod
    def _send(conn: socket.socket, status: int, out: bytes) -> None:
        reason = STATUS_TEXT.get(status, b"OK")
        hdr = (
            b"HTTP/1.1 %d %s\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\nServer: dexpot\r\n\r\n" % (status, reason, len(out))
        )
        conn.sendall(hdr + out)

    # ---- scheduling ----

    def _worker_gil(self) -> None:
        cond = self._cond
        while True:
            with cond:
                while not self._work:
                    cond.wait()
                conn, buf = self._work.popleft()
            try:
                while True:
                    keep_alive, buf = self._process(conn, buf)
                    if not keep_alive:
                        break
                conn.close()
            except (ConnectionError, OSError, ValueError):
                with contextlib.suppress(OSError):
                    conn.close()

    def _own_connection(self, conn: socket.socket, buf: bytes) -> None:
        try:
            while True:
                keep_alive, buf = self._process(conn, buf)
                if not keep_alive:
                    break
            conn.close()
        except (ConnectionError, OSError, ValueError):
            with contextlib.suppress(OSError):
                conn.close()

    def _handle_admission(self, conn: socket.socket, buf: bytes) -> None:
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
        mode = "unbounded-ft" if _gil_free else f"pooled-gil({POOL_SIZE})"
        print(f"dexpot serving on http://{host}:{port} pid={os.getpid()} mode={mode}", flush=True)
        if not _gil_free:
            for _ in range(POOL_SIZE):
                threading.Thread(target=self._worker_gil, daemon=True).start()
        while True:
            conn, _addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._handle_admission(conn, b"")

    def _accept_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _addr = srv.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._handle_admission(conn, b"")

    def _serve_multiprocess(self, host: str, port: int, n_workers: int) -> None:
        """GIL build: one worker process per DEXPOT_WORKERS, each with its own
        listener via SO_REUSEPORT (kernel load-balances connections).

        Workers are forked BEFORE any threads exist; each child then starts its
        own pool inside serve(). The parent only supervises.
        """
        listeners: list[socket.socket] = []
        for _ in range(n_workers):
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            else:  # pragma: no cover - Linux/macOS/Windows all have it on 3.12+
                srv.close()
                raise OSError("SO_REUSEPORT is required for multiprocess serving")
            srv.bind((host, port))
            srv.listen(SOCKET_BACKLOG)
            listeners.append(srv)

        print(
            f"dexpot serving on http://{host}:{port} pid={os.getpid()} "
            f"mode=pooled-gil({POOL_SIZE})x{n_workers}",
            flush=True,
        )

        procs: list[Any] = []
        for listener in listeners:
            proc = _multiprocessing.Process(target=self._worker_process, args=(listener,), daemon=True)
            proc.start()
            procs.append(proc)

        stopping = threading.Event()

        def stop(*_args: object) -> None:
            stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        try:
            while not stopping.is_set():
                for i, proc in enumerate(procs):
                    if not proc.is_alive():
                        print(f"dexpot worker {i} exited; restarting", flush=True)
                        listener = listeners[i]
                        proc = _multiprocessing.Process(target=self._worker_process, args=(listener,), daemon=True)
                        proc.start()
                        procs[i] = proc
                stopping.wait(1.0)
        finally:
            for proc in procs:
                proc.terminate()
            for proc in procs:
                proc.join(timeout=5)
            for listener in listeners:
                with contextlib.suppress(OSError):
                    listener.close()

    def _worker_process(self, listener: socket.socket) -> None:
        """Child entrypoint: adopt the inherited listener and serve forever."""
        if not _gil_free:
            for _ in range(POOL_SIZE):
                threading.Thread(target=self._worker_gil, daemon=True).start()
        while True:
            try:
                conn, _addr = listener.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._handle_admission(conn, b"")
