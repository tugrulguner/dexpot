"""A connection permit covers its owner's complete thread lifetime."""

import importlib
import socket
import threading

from dexpot import Dex

module = importlib.import_module("dexpot.app")


def test_finished_target_cannot_release_capacity_before_owner_thread_exits(monkeypatch):
    app = Dex()
    monkeypatch.setattr(module, "_gil_free", True)
    monkeypatch.setattr(module, "_FT_CONNECTION_SLOTS", threading.BoundedSemaphore(1))
    target_finished = threading.Event()
    allow_thread_exit = threading.Event()
    owners = []
    real_thread = threading.Thread

    class LingeringOwner(real_thread):
        def run(self):
            try:
                super().run()
            finally:
                target_finished.set()
                assert allow_thread_exit.wait(5)

    def make_owner(**kwargs):
        owner = LingeringOwner(**kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(module.threading, "Thread", make_owner)
    monkeypatch.setattr(app, "_process", lambda conn, buf: (False, b""))
    pairs = [socket.socketpair() for _ in range(3)]
    try:
        app._handle_admission(pairs[0][0], b"")
        assert target_finished.wait(2)
        assert owners[0].is_alive()
        assert not app._active_connections
        app._handle_admission(pairs[1][0], b"")
        assert len(owners) == 1, "replacement overlapped a still-live owner thread"
        assert pairs[1][1].recv(4096).startswith(b"HTTP/1.1 503 ")
        allow_thread_exit.set()
        owners[0].join(2)
        assert not owners[0].is_alive()
        app._handle_admission(pairs[2][0], b"")
        assert len(owners) == 2, "a fully exited owner must return admission capacity"
    finally:
        allow_thread_exit.set()
        for owner in owners:
            owner.join(2)
        app._begin_drain(timeout=0.1)
        for pair in pairs:
            for conn in pair:
                conn.close()
