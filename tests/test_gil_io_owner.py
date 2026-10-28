"""Bounded shared I/O ownership and independent-connection progress."""

import importlib
import socket
import threading

import pytest


def test_one_io_thread_owns_multiple_connections():
    try:
        module = importlib.import_module("dexpot._gil_io")
    except ModuleNotFoundError:
        raise AssertionError("shared process-level socket owner is not implemented") from None
    manager = module.SocketIO()
    pairs = [socket.socketpair() for _ in range(4)]
    try:
        proxies = [manager.connection(left) for left, _ in pairs]
        for proxy, (_, right) in zip(proxies, pairs, strict=True):
            proxy.settimeout(1)
            right.sendall(b"request")
            assert proxy.recv(128) == b"request"
            proxy.sendall(b"response")
            assert right.recv(128) == b"response"
        assert manager.thread.is_alive()
        assert all(proxy.io_thread is manager.thread for proxy in proxies)
    finally:
        manager.close()
        for left, right in pairs:
            left.close()
            right.close()
    assert not manager.thread.is_alive()


def test_close_releases_a_pending_receive():
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    left, right = socket.socketpair()
    proxy = manager.connection(left)
    proxy.settimeout(30)
    started = threading.Event()
    errors = []

    def waiting():
        started.set()
        try:
            proxy.recv(128)
        except OSError as exc:
            errors.append(exc)

    worker = threading.Thread(target=waiting)
    try:
        worker.start()
        assert started.wait(1)
        manager.close()
        worker.join(2)
        assert not worker.is_alive() and errors
    finally:
        manager.close()
        left.close()
        right.close()
        worker.join(2)


def test_wakeup_creation_failure_closes_selector(monkeypatch):
    module = importlib.import_module("dexpot._gil_io")
    selector = module.selectors.DefaultSelector()
    monkeypatch.setattr(module.selectors, "DefaultSelector", lambda: selector)

    def fail():
        raise OSError("injected wakeup allocation failure")

    monkeypatch.setattr(module.socket, "socketpair", fail)
    try:
        with pytest.raises(OSError, match="injected wakeup"):
            module.SocketIO()
        assert selector.get_map() is None, "selector leaked before worker startup"
    finally:
        selector.close()


def test_failed_connection_close_remains_owned_until_shutdown():
    module = importlib.import_module("dexpot._gil_io")
    left, right = socket.socketpair()

    class InterruptedClose(socket.socket):
        fail_close = True

        def close(self):
            if self.fail_close:
                self.fail_close = False
                raise OSError("injected close failure")
            return super().close()

    raw = InterruptedClose(fileno=left.detach())
    manager = module.SocketIO()
    proxy = manager.connection(raw)
    try:
        with pytest.raises(OSError, match="injected close"):
            proxy.close()
        manager.close()
        assert raw.fileno() == -1, "failed close lost the manager's socket ownership"
    finally:
        manager.close()
        raw.close()
        right.close()


def test_select_limited_platform_retains_incumbent_pool(monkeypatch):
    import dexpot.app as app_module

    module = importlib.import_module("dexpot._gil_io")

    def forbidden():
        raise AssertionError("select-limited platform must not acquire the shared owner")

    monkeypatch.setattr(module, "SocketIO", forbidden)
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    # Exercise backend selection without launching unrelated worker threads.
    monkeypatch.setattr(app_module, "POOL_SIZE", 0)
    app = app_module.Dex()
    with socket.socket() as listener:
        app._start_gil_workers(listener)
    assert getattr(app, "_gil_io", None) is None


def test_stalled_write_has_total_deadline_and_does_not_block_a_peer():
    module = importlib.import_module("dexpot._gil_io")
    manager = module.SocketIO()
    first, unread = socket.socketpair()
    second, reader = socket.socketpair()
    first.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    slow, fast = manager.connection(first), manager.connection(second)
    slow.settimeout(0.05)
    fast.settimeout(1)
    reader.settimeout(1)
    started = threading.Event()
    errors = []

    def writing():
        started.set()
        try:
            slow.sendall(b"x" * (4 * 1024 * 1024))
        except TimeoutError as exc:
            errors.append(exc)

    worker = threading.Thread(target=writing)
    try:
        worker.start()
        assert started.wait(1)
        fast.sendall(b"peer-progress")
        assert reader.recv(128) == b"peer-progress"
        worker.join(2)
        assert not worker.is_alive() and errors
    finally:
        manager.close()
        for peer in (first, unread, second, reader):
            peer.close()
        worker.join(2)
