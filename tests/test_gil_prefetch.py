"""A ready-I/O owner delivers bytes without a per-read command round trip."""

import importlib
import socket


def test_receive_uses_owner_prefetch_instead_of_a_worker_rpc(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    left, right = socket.socketpair()
    proxy = manager.connection(left)
    call = manager.call

    def no_receive_command(conn, operation, argument, timeout):
        assert operation != "recv", "worker receive still requires an I/O-owner command round trip"
        return call(conn, operation, argument, timeout)

    monkeypatch.setattr(manager, "call", no_receive_command)
    try:
        proxy.settimeout(1)
        right.sendall(b"fragment-one")
        assert proxy.recv(128) == b"fragment-one"
        right.sendall(b"fragment-two")
        assert proxy.recv(128) == b"fragment-two"
    finally:
        manager.close()
        left.close()
        right.close()
