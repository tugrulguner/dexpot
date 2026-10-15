import errno
import socket

import pytest

from dexpot import _gil_idle
from dexpot import app as module
from dexpot.app import Dex


@pytest.mark.skipif(module._gil_free, reason="GIL readiness resource ownership")
@pytest.mark.parametrize("stage", ["socketpair", "register", "thread_constructor"])
def test_readiness_partial_initialization_releases_resources(monkeypatch, stage):
    selectors = []
    sockets = []
    factory = _gil_idle.selectors.DefaultSelector
    pair = socket.socketpair

    def fail(*args, **kwargs):
        raise OSError(errno.EMFILE, "injected readiness allocation failure")

    def selector():
        value = factory()
        selectors.append(value)
        if stage == "register":
            monkeypatch.setattr(value, "register", fail)
        return value

    def socketpair():
        if stage == "socketpair":
            return fail()
        result = pair()
        sockets.extend(result)
        return result

    monkeypatch.setattr(_gil_idle.selectors, "DefaultSelector", selector)
    monkeypatch.setattr(_gil_idle.socket, "socketpair", socketpair)
    if stage == "thread_constructor":
        monkeypatch.setattr(_gil_idle.threading, "Thread", fail)
    try:
        with pytest.raises(OSError, match="injected readiness"):
            _gil_idle.GILIdleHub(Dex(), 2, 2, 10)
        assert all(value.get_map() is None for value in selectors)
        assert all(value.fileno() == -1 for value in sockets)
    finally:
        for value in selectors:
            value.close()
        for value in sockets:
            value.close()


@pytest.mark.skipif(module._gil_free, reason="GIL shared-listener resource ownership")
def test_parent_event_allocation_failure_releases_real_listener(monkeypatch):
    app = Dex()
    sockets = []
    factory = socket.socket

    def capture(*args, **kwargs):
        value = factory(*args, **kwargs)
        sockets.append(value)
        return value

    def fail():
        raise OSError(errno.EMFILE, "injected IPC allocation failure")

    monkeypatch.setattr(module.socket, "socket", capture)
    monkeypatch.setattr(module._multiprocessing, "Event", fail)
    try:
        with pytest.raises(OSError, match="injected IPC"):
            app._serve_multiprocess("127.0.0.1", 0, 2)
        assert sockets and all(value.fileno() == -1 for value in sockets)
        assert app._shared_listener is None
        assert app._worker_accept_gate is None
    finally:
        for value in sockets:
            value.close()
