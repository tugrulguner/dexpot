"""The Dex application: routing, validation, and the serving loop.

Ported from the gilpot-bench spike (micro6) with the same measured architecture:
- connection-owning threads, no asyncio
- mode-adaptive scheduling (bounded connection-owning threads on free-threaded CPython,
  bounded pool + fast-shed on GIL builds)
- msgspec fused decode+validate for typed bodies
- single-write responses
"""

from __future__ import annotations

import contextlib
import http
import logging
import multiprocessing
import os
import signal
import socket
import sys
import sysconfig
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, cast

import msgspec

from ._http import ClientDisconnected, HttpLimits, HTTPParseError, read_request
from ._plans import (
    ApplicationPlan,
    EndpointPlan,
    RouterPlan,
    _ApplicationCompilationDuringRegistration,
    _handler_signature,
)
from ._preparation_policy import darwin_policy
from .requests import Request
from .responses import RawResponse, Response

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
_POOL_AUTOMATIC = int(os.environ.get("DEXPOT_POOL", "0")) == 0
_QUEUE_AUTOMATIC = "DEXPOT_MAX_QUEUE" not in os.environ
MAX_QUEUE = int(os.environ.get("DEXPOT_MAX_QUEUE", str(POOL_SIZE * 2)))
MAX_CONNECTIONS = int(os.environ.get("DEXPOT_MAX_CONNECTIONS", "1024"))
if POOL_SIZE <= 0:
    raise ValueError("DEXPOT_POOL must be positive, or zero for automatic sizing")
if MAX_QUEUE <= 0:
    raise ValueError("DEXPOT_MAX_QUEUE must be positive")
if MAX_CONNECTIONS <= 0:
    raise ValueError("DEXPOT_MAX_CONNECTIONS must be positive")
_FT_CONNECTION_SLOTS = threading.BoundedSemaphore(MAX_CONNECTIONS) if _gil_free else None
_RUNTIME_BINDING_LOCK = threading.Lock()
_FT_OWNERS_LOCK = threading.RLock()
_FT_OWNERS: dict[threading.Thread, tuple[Dex, threading.BoundedSemaphore]] = {}


def _reap_ft_owners() -> None:
    """Caller holds the registry lock; return permits only after native join."""
    for owner, (_app, slots) in tuple(_FT_OWNERS.items()):
        if owner.ident is not None and not owner.is_alive():
            owner.join()
            del _FT_OWNERS[owner]
            slots.release()


_json_encode = msgspec.json.encode
_logger = logging.getLogger("dexpot.error")
_BODYLESS_STATUSES = frozenset({204, 205, 304})


def _handler_response(status: object, out: bytes) -> tuple[int, bytes]:
    """Validate a final application response before it reaches the wire."""
    if type(status) is not int or not 200 <= status <= 599:
        raise ValueError("handler response status must be an integer from 200 to 599")
    if status in _BODYLESS_STATUSES:
        out = b""
    return status, out


class HTTPError(Exception):
    """Raise from a handler to return an error status with a JSON detail."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def _path_segments(path: str) -> list[str]:
    if path == "/":
        return []
    return path[1:].split("/")


class Dex:
    """The application. ``@dex.get(...)`` / ``@dex.post(...)`` register routes."""

    def __init__(self, *, limits: HttpLimits | None = None) -> None:
        self.limits = limits or HttpLimits()
        self._literal: dict[tuple[str, str], EndpointPlan] = {}
        self._parametric: list[tuple[str, list[str], EndpointPlan]] = []
        self._endpoints: list[EndpointPlan] = []
        self._plan: ApplicationPlan | None = None
        self._declaration_lock = threading.RLock()
        self._registration_depth = 0
        self._work: deque[tuple[socket.socket, bytes]] = deque()
        self._cond = threading.Condition()
        self._stopping = threading.Event()
        self._active_connections: set[socket.socket] = set()
        self._runtime_bound = False
        self._serving_gil_free = _gil_free
        self._response_turn_handoff = False
        self._response_turn_cpu_budget_ns = 0
        self._response_owner_policy = None
        self._response_owner_policy_selected = False
        self._handoff_yield = None
        self._pool_size = POOL_SIZE
        self._max_queue = MAX_QUEUE
        self._runtime_mode_warning_logged = False

    def _bind_runtime(self) -> None:
        """Bind the scheduler once after application imports, before route compilation."""
        global _FT_CONNECTION_SLOTS
        if self._runtime_bound:
            return
        enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
        self._serving_gil_free = not enabled
        self._handoff_yield = getattr(os, "sched_yield", None)
        self._response_turn_handoff = (
            sys.platform == "darwin" and self._serving_gil_free and self._handoff_yield is not None
        )
        self._response_turn_cpu_budget_ns = 1_000_000 if self._response_turn_handoff else 0
        if sys.platform == "darwin" and self._serving_gil_free:
            self._response_owner_policy = darwin_policy()
            self._response_owner_policy_selected = self._response_owner_policy is not None
        self._pool_size = POOL_SIZE
        self._max_queue = MAX_QUEUE
        if self._serving_gil_free != _gil_free:
            if _POOL_AUTOMATIC:
                self._pool_size = _cores if self._serving_gil_free else _cores * 2 + 2
            if _QUEUE_AUTOMATIC:
                self._max_queue = self._pool_size * 2
        if self._serving_gil_free:
            with _RUNTIME_BINDING_LOCK:
                if _FT_CONNECTION_SLOTS is None:
                    _FT_CONNECTION_SLOTS = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._runtime_bound = True

    def _runtime_info(self) -> dict[str, Any]:
        """Return an explicit diagnostic snapshot; never used in request dispatch."""
        enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
        return {
            "pid": os.getpid(),
            "python": sys.version,
            "free_threaded_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            "gil_enabled": enabled,
            "selected_gil_enabled": not self._serving_gil_free if self._runtime_bound else None,
            "execution_mode": ("bounded-ft" if self._serving_gil_free else "pooled-gil")
            if self._runtime_bound
            else "unbound",
            "pool_size": self._pool_size,
            "max_queue": self._max_queue,
            "connection_limit": MAX_CONNECTIONS,
            "response_turn_handoff": self._response_turn_handoff,
            "response_turn_cpu_budget_ns": self._response_turn_cpu_budget_ns,
            "response_owner_policy_selected": self._response_owner_policy_selected,
        }

    def _runtime_description(self) -> str:
        info = self._runtime_info()
        build = "free-threaded Python" if info["free_threaded_build"] else "standard Python"
        return f"{build}, GIL {'enabled' if info['gil_enabled'] else 'disabled'}"

    def _check_runtime_mode(self) -> None:
        if self._runtime_bound and not self._runtime_mode_warning_logged:
            enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
            if enabled != (not self._serving_gil_free):
                self._runtime_mode_warning_logged = True
                _logger.warning(
                    "GIL state changed after startup; retaining %s execution. Restart after loading application dependencies to reselect the runtime.",
                    "bounded-ft" if self._serving_gil_free else "pooled-gil",
                )

    # ---- route registration ----

    def _register(
        self,
        method: str,
        path: str,
        fn: Callable[..., Any],
        body_type: Any,
        resp_type: Any,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[..., Any]:
        with self._declaration_lock:
            self._registration_depth += 1
            try:
                return self._register_locked(
                    method,
                    path,
                    fn,
                    body_type,
                    resp_type,
                    annotation_locals,
                )
            finally:
                self._registration_depth -= 1

    def _register_locked(
        self,
        method: str,
        path: str,
        fn: Callable[..., Any],
        body_type: Any,
        resp_type: Any,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[..., Any]:
        if self._plan is not None:
            raise RuntimeError("application is compiled; routes can no longer be registered")
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("route paths must be absolute paths without a query or fragment")
        path_names = [
            s[1:-1] for s in _path_segments(path) if s.startswith("{") and s.endswith("}")
        ]
        route = EndpointPlan(
            method,
            path,
            fn,
            body_type,
            resp_type,
            (fn.__doc__ or "").strip(),
            path_names,
            annotation_locals,
        )
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
        self._endpoints.append(route)
        return fn

    def get(
        self, path: str, response: Any = None, *, annotation_locals: Mapping[str, Any] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("GET", path, None, response, annotation_locals)

    def post(
        self,
        path: str,
        body: Any = None,
        response: Any = None,
        *,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("POST", path, body, response, annotation_locals)

    def put(
        self,
        path: str,
        body: Any = None,
        response: Any = None,
        *,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("PUT", path, body, response, annotation_locals)

    def patch(
        self,
        path: str,
        body: Any = None,
        response: Any = None,
        *,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("PATCH", path, body, response, annotation_locals)

    def delete(
        self, path: str, response: Any = None, *, annotation_locals: Mapping[str, Any] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._method_decorator("DELETE", path, None, response, annotation_locals)

    def _method_decorator(
        self,
        method: str,
        path: str,
        body: Any,
        response: Any,
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        # Snapshot explicit bindings, never infer provenance from a caller frame.
        namespace = dict(annotation_locals) if annotation_locals is not None else None

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            body_type = body
            if body_type is None:
                # fall back to live annotation object if present (no __future__ import)
                hints = {
                    name: parameter.annotation
                    for name, parameter in _handler_signature(fn).parameters.items()
                }
                for ann in hints.values():
                    if (
                        ann is not Request
                        and isinstance(ann, type)
                        and issubclass(ann, msgspec.Struct)
                    ):
                        body_type = ann
                        break
            return self._register(method, path, fn, body_type, response, namespace)

        return deco

    # ---- matching ----

    def _compile(self) -> ApplicationPlan:
        """Compile declarations once into the immutable plan used by traffic."""
        plan = self._plan
        if plan is not None:
            return plan
        with self._declaration_lock:
            if self._registration_depth:
                raise _ApplicationCompilationDuringRegistration(
                    "application cannot be compiled while route registration is in progress"
                )
            if self._plan is not None:
                return self._plan
            router = RouterPlan.compile(self._literal, self._parametric)
            self._plan = ApplicationPlan(
                endpoints=tuple(self._endpoints),
                router=router,
            )
            return self._plan

    def _match(
        self, method: str, path: str
    ) -> tuple[EndpointPlan | None, list[Any] | None, tuple[str, ...]]:
        plan = self._plan
        if plan is None:
            plan = self._compile()
        router = plan.router
        hit = router.literal.get((method, path))
        if hit is not None:
            return hit, [], ()
        return router.match_after_literal_miss(method, path)

    # ---- request processing ----

    def _process(
        self, conn: socket.socket, buf: bytes, *, head_deadline: float | None = None
    ) -> tuple[bool, bytes]:
        try:
            request, buf = (
                read_request(conn, buf, self.limits)
                if head_deadline is None
                else read_request(conn, buf, self.limits, head_deadline=head_deadline)
            )
        except ClientDisconnected:
            return False, b""
        except HTTPParseError as exc:
            if head_deadline is not None:
                # The Darwin commit-gated reader spent the request budget;
                # its queued error response uses the configured write timeout.
                conn.settimeout(self.limits.idle_read_seconds)
            self._send(
                conn,
                exc.status,
                _json_encode({"detail": exc.detail}),
                keep_alive=False,
                version=exc.version or "HTTP/1.1",
                suppress_body=exc.suppress_body,
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
                    suppress_body=request.method == "HEAD",
                    extra_headers=(("Allow", ", ".join(allowed)),),
                )
            else:
                self._send(
                    conn,
                    404,
                    _json_encode({"detail": "not found"}),
                    keep_alive=request.keep_alive,
                    version=request.version,
                    suppress_body=request.method == "HEAD",
                )
            return request.keep_alive, buf

        extra_headers = ()
        content_type = "application/json"
        try:
            request_params = (
                dict(zip(route.path_names, captures_list, strict=True))
                if route.needs_request
                else None
            )
            # Convert typed captures before the endpoint's compiled direct call.
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
                        suppress_body=request.method == "HEAD",
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
                        suppress_body=request.method == "HEAD",
                    )
                    return request.keep_alive, buf

            if route.needs_request:
                assert request_params is not None
                context = Request(
                    request.method,
                    request.path,
                    request_params,
                    request.query,
                    request.headers,
                    request.body,
                    body_arg,
                )
                result = route.invoke(captures_list, body_arg, context)
            else:
                result = route.invoke(captures_list, body_arg)
            if isinstance(result, Response):
                status = result.status
                if isinstance(result, RawResponse):
                    if route.resp_type is not None:
                        raise TypeError("raw responses cannot bypass response= schemas")
                    out = result.body
                elif result.body is None and status in _BODYLESS_STATUSES:
                    out = b""
                else:
                    out = route.encode(result.body)
                status, out = _handler_response(status, out)
                # Publish metadata only after every fallible preparation step.
                extra_headers = result.headers
                if isinstance(result, RawResponse):
                    content_type = result.content_type
            else:
                if isinstance(result, tuple):
                    status, payload = result
                    out = route.encode(payload)
                else:
                    status, out = 200, route.encode(result)
                status, out = _handler_response(status, out)
        except HTTPError as exc:
            try:
                status, out = _handler_response(exc.status, _json_encode({"detail": exc.detail}))
            except (TypeError, ValueError):
                _logger.exception(
                    "invalid HTTPError status while processing %s %s",
                    request.method,
                    request.path,
                )
                status = 500
                out = _json_encode({"detail": "internal server error"})
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
            suppress_body=request.method == "HEAD",
            extra_headers=extra_headers,
            content_type=content_type,
        )
        return request.keep_alive, buf

    @staticmethod
    def _send(
        conn: socket.socket,
        status: object,
        out: bytes,
        *,
        keep_alive: bool,
        version: str = "HTTP/1.1",
        extra_headers: tuple[tuple[str, str], ...] = (),
        suppress_body: bool = False,
        content_type: str = "application/json",
    ) -> None:
        if type(status) is not int or not 100 <= status <= 599:
            _logger.error("invalid response status %r; sending 500", status)
            status = 500
            out = _json_encode({"detail": "internal server error"})
            keep_alive = False
        informational = 100 <= status < 200
        if suppress_body or informational or status in _BODYLESS_STATUSES:
            out = b""
        try:
            reason = http.HTTPStatus(status).phrase.encode("ascii")
        except ValueError:
            reason = b""
        # 1xx and 204 forbid Content-Length. For 304 it would describe the
        # selected 200 representation, which dexpot cannot infer, so omit it.
        omit_length = suppress_body or informational or status in (204, 304)
        header = b"%s %d %s\r\nServer: dexpot\r\nConnection: %s\r\n" % (
            version.encode("ascii"),
            status,
            reason,
            b"keep-alive" if keep_alive else b"close",
        )
        if not omit_length:
            header += b"Content-Type: %s\r\nContent-Length: %d\r\n" % (
                content_type.encode("latin-1"),
                len(out),
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
                owner = getattr(self, "_gil_io", None)
                channel = (
                    owner.connection(conn)
                    if owner is not None and type(conn) is socket.socket
                    else None
                )
                pipeline = channel is not None and sys.platform == "darwin"
                if channel is not None:
                    channel.pipeline = pipeline
                transport = cast(socket.socket, channel) if channel is not None else conn
                try:
                    while not self._stopping.is_set():
                        if pipeline and channel is not None:
                            deadline = channel.wait_request(
                                self.limits.head_read_seconds,
                                self.limits.idle_read_seconds,
                                buffered=bool(buf),
                            )
                            keep_alive, buf = self._process(transport, buf, head_deadline=deadline)
                        else:
                            keep_alive, buf = self._process(transport, buf)
                        if not keep_alive:
                            break
                finally:
                    transport.close()
            except (ConnectionError, OSError, ValueError):
                with contextlib.suppress(OSError):
                    conn.close()
            finally:
                with cond:
                    self._active_connections.discard(conn)
                    cond.notify_all()

    def _start_gil_workers(self, listener: socket.socket) -> None:
        """Roll back a partially started pool before propagating startup failure."""
        from ._gil_io import SocketIO

        workers: list[threading.Thread] = []
        io_owner = None
        try:
            previous = getattr(self, "_gil_io", None)
            if previous is not None and previous.thread.is_alive():
                raise RuntimeError("previous GIL I/O owner is still draining")
            # Windows' select backend has a descriptor-set ceiling below supported
            # configured pool sizes; retain its incumbent connection-owner path.
            if sys.platform != "win32":
                io_owner = SocketIO()
                self._gil_io = io_owner
            pool_size = self._pool_size if self._runtime_bound else POOL_SIZE
            for _ in range(pool_size):
                worker = threading.Thread(target=self._worker_gil, daemon=True)
                worker.start()
                workers.append(worker)
        except BaseException:
            with contextlib.suppress(OSError):
                listener.close()
            try:
                self._begin_drain(timeout=0)
            finally:
                deadline = time.monotonic() + 1.0
                for worker in workers:
                    worker.join(timeout=max(0.0, deadline - time.monotonic()))
                if io_owner is not None:
                    io_owner.close(timeout=max(0.0, deadline - time.monotonic()))
            raise

    def _own_connection(self, conn: socket.socket, buf: bytes, *, registered: bool = False) -> None:
        if not registered:
            with self._cond:
                self._active_connections.add(conn)
        try:
            handoff_enabled = self._response_turn_handoff
            cpu_budget_ns = self._response_turn_cpu_budget_ns
            yield_turn = self._handoff_yield
            cpu_turn_start = (
                time.thread_time_ns() if handoff_enabled and cpu_budget_ns and yield_turn else 0
            )
            while not self._stopping.is_set():
                keep_alive, buf = self._process(conn, buf)
                if not keep_alive:
                    break
                if handoff_enabled and cpu_budget_ns and yield_turn is not None:
                    cpu_now = time.thread_time_ns()
                    if cpu_now - cpu_turn_start >= cpu_budget_ns:
                        yield_turn()
                        cpu_turn_start = cpu_now
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()
            with self._cond:
                self._active_connections.discard(conn)
                self._cond.notify_all()

    def _own_connection_ft(self, conn: socket.socket, buf: bytes) -> None:
        # The admitting thread reaps/join()s this owner before returning its
        # permit. Releasing here would allow a replacement before thread exit.
        policy = self._response_owner_policy
        previous = -1
        changed = False
        owner_started = False
        try:
            previous = policy.current() if policy is not None else -1
            changed = policy is not None and previous == 1 and policy.set(0) == 0
            owner_started = True
            self._own_connection(conn, buf, registered=True)
        finally:
            if not owner_started:
                with contextlib.suppress(OSError):
                    conn.close()
                with self._cond:
                    self._active_connections.discard(conn)
                    self._cond.notify_all()
            if changed and policy is not None and policy.set(previous) != 0:
                raise RuntimeError("could not restore owner scheduling policy")

    @staticmethod
    def _reject_overload(conn: socket.socket) -> None:
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

    def _handle_admission(self, conn: socket.socket, buf: bytes) -> None:
        if self._stopping.is_set():
            with contextlib.suppress(OSError):
                conn.close()
            return
        if self._serving_gil_free:
            slots = _FT_CONNECTION_SLOTS
            assert slots is not None
            acquired = False
            registered = False
            owner_started = False
            start_failed = False
            try:
                with _FT_OWNERS_LOCK:
                    _reap_ft_owners()
                    acquired = slots.acquire(blocking=False)
                    if not acquired:
                        start_failed = True
                    else:
                        with self._cond:
                            if not self._stopping.is_set():
                                self._active_connections.add(conn)
                                registered = True
                        if registered:
                            owner = threading.Thread(
                                target=self._own_connection_ft,
                                args=(conn, buf),
                                daemon=True,
                            )
                            # Publish before start while holding the registry
                            # lock: neither a fast exit nor a concurrent app can
                            # race an unregistered/unstarted owner.
                            _FT_OWNERS[owner] = (self, slots)
                            try:
                                owner.start()
                            except BaseException as exc:
                                del _FT_OWNERS[owner]
                                if not isinstance(exc, RuntimeError):
                                    raise
                                start_failed = True
                            else:
                                owner_started = True
                                _reap_ft_owners()
            finally:
                if not owner_started:
                    try:
                        if start_failed:
                            self._reject_overload(conn)
                        else:
                            with contextlib.suppress(OSError):
                                conn.close()
                    finally:
                        try:
                            with self._cond:
                                self._active_connections.discard(conn)
                                self._cond.notify_all()
                        finally:
                            if acquired:
                                slots.release()
            return
        # GIL build: bounded pool + fast-shed on saturation.
        with self._cond:
            saturated = len(self._work) >= (self._max_queue if self._runtime_bound else MAX_QUEUE)
            if not saturated:
                self._work.append((conn, buf))
                self._cond.notify()
        if saturated:
            self._reject_overload(conn)

    # ---- serving ----

    def _make_listener(self, host: str, reuseport: bool) -> socket.socket:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if reuseport and hasattr(socket, "SO_REUSEPORT"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        return srv

    def serve(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self._bind_runtime()
        self._compile()
        workers_env = os.environ.get("DEXPOT_WORKERS", "")
        n_workers = max(1, int(workers_env)) if workers_env.isdigit() else 0

        if not self._serving_gil_free and n_workers > 1:
            self._serve_multiprocess(host, port, n_workers)
            return

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
                self._check_runtime_mode()
                continue
            self._check_runtime_mode()
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
        with _FT_OWNERS_LOCK:
            owners = [owner for owner, (app, _slots) in _FT_OWNERS.items() if app is self]
        for owner in owners:
            if owner.ident is not None:
                owner.join(timeout=max(0.0, deadline - time.monotonic()))
        with _FT_OWNERS_LOCK:
            _reap_ft_owners()

        io_owner = getattr(self, "_gil_io", None)
        if io_owner is not None:
            io_owner.close(timeout=max(0.0, deadline - time.monotonic()))

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
            f"mode=pooled-gil({self._pool_size})x{n_workers} runtime={self._runtime_description()}",
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
        self._bind_runtime()
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

        self._start_gil_workers(listener)
        try:
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
