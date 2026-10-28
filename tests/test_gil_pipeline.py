"""Mac pipeline mode queues responses without a synchronous write RPC."""

import importlib
import socket
import time

import pytest


def test_reader_keeps_forwarded_head_deadline_instead_of_resetting_it():
    module = importlib.import_module("dexpot._gil_io")
    http = importlib.import_module("dexpot._http")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    proxy = owner.connection(left)
    try:
        with pytest.raises(http.HTTPParseError) as raised:
            http.read_request(proxy, b"", http.HttpLimits(), head_deadline=time.monotonic() - 1)
        assert raised.value.status == 408
    finally:
        owner.close()
        left.close()
        right.close()


def test_pipeline_response_does_not_roundtrip_through_blocking_call(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    proxy = owner.connection(left)
    proxy.pipeline = True
    original = owner.call

    def no_write_rpc(conn, operation, argument, timeout):
        assert operation != "sendall", "pipeline response still waits for a synchronous write RPC"
        return original(conn, operation, argument, timeout)

    monkeypatch.setattr(owner, "call", no_write_rpc)
    try:
        proxy.settimeout(1)
        right.settimeout(1)
        proxy.sendall(b"complete-response")
        proxy.close()
        assert right.recv(128) == b"complete-response"
        assert right.recv(128) == b""
    finally:
        owner.close()
        left.close()
        right.close()


def test_idle_deadline_arms_after_a_silent_write_completion(monkeypatch):
    import threading

    module = importlib.import_module("dexpot._gil_io")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    proxy = owner.connection(left)
    proxy.pipeline = True
    proxy.settimeout(1)
    release = threading.Event()
    waiting = threading.Event()
    done = threading.Event()
    errors = []
    advance = owner._advance
    condition_wait = proxy._state.condition.wait

    def hold_write(task):
        if task.operation == "sendall":
            release.wait(1)
        advance(task)

    def observe_wait(timeout=None):
        waiting.set()
        return condition_wait(timeout)

    def await_request():
        try:
            proxy.wait_request(head_seconds=0.05, idle_seconds=0.02)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    monkeypatch.setattr(owner, "_advance", hold_write)
    monkeypatch.setattr(proxy._state.condition, "wait", observe_wait)
    worker = threading.Thread(target=await_request)
    try:
        proxy.sendall(b"response")
        worker.start()
        assert waiting.wait(1)
        release.set()
        assert done.wait(0.2), "write completion left the worker asleep past its read deadline"
        assert not errors
    finally:
        release.set()
        owner.close()
        left.close()
        right.close()
        worker.join(1)


def test_pipeline_idle_wait_does_not_restart_idle_budget(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    http = importlib.import_module("dexpot._http")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    proxy = owner.connection(left)
    proxy.pipeline = True
    proxy.settimeout(1)
    try:
        right.settimeout(1)
        proxy.sendall(b"response")
        assert right.recv(128) == b"response"
        deadline = proxy.wait_request(head_seconds=1, idle_seconds=0.01)

        def forbidden_wait(*args, **kwargs):
            raise AssertionError("parser restarted an already expired idle wait")

        monkeypatch.setattr(proxy._state.condition, "wait", forbidden_wait)
        with pytest.raises(http.HTTPParseError) as raised:
            http.read_request(
                proxy, b"", http.HttpLimits(idle_read_seconds=0.01), head_deadline=deadline
            )
        assert raised.value.status == 408
    finally:
        owner.close()
        left.close()
        right.close()


def test_pipeline_close_flushes_a_partial_write_before_eof():
    import threading

    module = importlib.import_module("dexpot._gil_io")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    proxy = owner.connection(left)
    proxy.pipeline = True
    proxy.settimeout(2)
    right.settimeout(2)
    payload = bytes(range(256)) * 513
    received = bytearray()

    def consume():
        while chunk := right.recv(4096):
            received.extend(chunk)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        proxy.sendall(payload)
        proxy.close()
        worker.join(2)
        assert not worker.is_alive() and received == payload
    finally:
        owner.close()
        left.close()
        right.close()
        worker.join(2)


def test_pipeline_does_not_dispatch_buffered_request_before_write_failure():
    import contextlib

    import pytest

    module = importlib.import_module("dexpot._gil_io")
    owner = module.SocketIO()
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    proxy = owner.connection(left)
    proxy.pipeline = True
    proxy.settimeout(0.05)
    try:
        proxy.sendall(b"x" * (4 * 1024 * 1024))
        right.sendall(b"next-request")
        with pytest.raises(TimeoutError):
            proxy.wait_request(head_seconds=1, idle_seconds=1, buffered=False)
    finally:
        with contextlib.suppress(OSError):
            proxy.close()
        owner.close()
        left.close()
        right.close()
