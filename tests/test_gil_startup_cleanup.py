import socket
import threading

import pytest

from dexpot import app as module
from dexpot.app import Dex


@pytest.mark.skipif(module._gil_free, reason="GIL startup policy")
def test_worker_start_failure_stops_started_readiness_owner(monkeypatch):
    app = Dex()
    monkeypatch.setattr(module, "POOL_SIZE", 2)
    monkeypatch.setenv("DEXPOT_WORKERS", "1")
    original = threading.Thread.start
    started = []
    count = 0

    def start(thread):
        nonlocal count
        count += 1
        if count == 3:
            raise RuntimeError("injected worker start failure")
        original(thread)
        started.append(thread)

    monkeypatch.setattr(threading.Thread, "start", start)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="injected worker"):
            app.serve("127.0.0.1", port)
        assert app._gil_hub is not None
        assert not app._gil_hub.thread.is_alive()
        assert all(not thread.is_alive() for thread in started)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    finally:
        app._begin_drain(timeout=0)
        for thread in started:
            thread.join(timeout=1)


@pytest.mark.skipif(module._gil_free, reason="GIL startup policy")
def test_readiness_start_failure_closes_its_socket_resources(monkeypatch):
    app = Dex()
    monkeypatch.setenv("DEXPOT_WORKERS", "1")
    failed = []

    def start(thread):
        failed.append(thread)
        raise RuntimeError("injected readiness start failure")

    monkeypatch.setattr(threading.Thread, "start", start)
    with pytest.raises(RuntimeError, match="injected readiness"):
        app.serve("127.0.0.1", 0)
    target = failed[0]._target
    hub = target.__self__
    assert hub.closed
    assert hub.reader.fileno() == -1 and hub.writer.fileno() == -1
