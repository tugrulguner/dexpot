"""Buffered receive bounds, EOF ordering and asynchronous failure cleanup."""

import importlib
import socket
import threading
from types import SimpleNamespace

import pytest


def test_late_publication_while_acquiring_buffer_lock_does_not_extend_deadline(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    left, right = socket.socketpair()
    state = module._Prefetch(left, left.fileno())

    class LatePublication(threading.Condition):
        def __enter__(self):
            result = super().__enter__()
            state.data.extend(b"late")
            state.available_at = 102.0
            return result

    state.condition = LatePublication()
    proxy = module.SocketOwner(SimpleNamespace(thread=None), state, 1)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    try:
        with pytest.raises(TimeoutError):
            proxy.recv(128)
    finally:
        left.close()
        right.close()


def test_prefetch_stops_at_cap_and_resumes_after_consumption():
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    left, right = socket.socketpair()
    proxy = manager.connection(left)
    state = proxy._state
    payload = bytes(range(256)) * 513
    worker = threading.Thread(target=right.sendall, args=(payload,))
    try:
        proxy.settimeout(1)
        worker.start()
        with state.condition:
            assert state.condition.wait_for(lambda: len(state.data) == state.limit, timeout=1)
            assert len(state.data) == 65536
        received = bytearray()
        while len(received) < len(payload):
            received.extend(proxy.recv(8192))
        assert received == payload
        worker.join(1)
        assert not worker.is_alive()
    finally:
        manager.close()
        left.close()
        right.close()
        worker.join(1)


def test_buffered_bytes_precede_eof_and_halfclose_allows_response():
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    left, right = socket.socketpair()
    proxy = manager.connection(left)
    try:
        proxy.settimeout(1)
        right.settimeout(1)
        right.sendall(b"request")
        right.shutdown(socket.SHUT_WR)
        assert proxy.recv(128) == b"request"
        assert proxy.recv(128) == b""
        proxy.sendall(b"response")
        assert right.recv(128) == b"response"
    finally:
        manager.close()
        left.close()
        right.close()


def test_failed_async_resume_releases_receiver_with_its_error(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    left, right = socket.socketpair()
    proxy = manager.connection(left)
    state = proxy._state
    register = manager._selector.register

    def failing_register(fileobj, events, data=None):
        if fileobj is left:
            raise OSError("injected read-resume registration failure")
        return register(fileobj, events, data)

    try:
        proxy.settimeout(0.2)
        right.sendall(b"x" * state.limit)
        with state.condition:
            assert state.condition.wait_for(lambda: len(state.data) == state.limit, timeout=1)
        monkeypatch.setattr(manager._selector, "register", failing_register)
        assert len(proxy.recv(state.limit)) == state.limit
        with pytest.raises(OSError, match="injected read-resume"):
            proxy.recv(1)
    finally:
        manager.close()
        left.close()
        right.close()
