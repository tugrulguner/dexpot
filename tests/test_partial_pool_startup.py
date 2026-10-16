import contextlib
import socket
import threading

import pytest

from dexpot import app as module
from dexpot.app import Dex


@pytest.mark.skipif(module._gil_free, reason="GIL worker-pool startup")
@pytest.mark.parametrize("entry", ["serve", "child"])
@pytest.mark.parametrize("fail_at", [1, 2])
def test_partial_pool_startup_closes_listener_and_joins_workers(monkeypatch, entry, fail_at):
    app = Dex()
    monkeypatch.setattr(module, "POOL_SIZE", 2)
    monkeypatch.setenv("DEXPOT_WORKERS", "1")
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    original = threading.Thread.start
    started = []
    count = 0
    error = None

    def start(worker):
        nonlocal count
        count += 1
        if count == fail_at:
            raise RuntimeError("injected worker start failure")
        original(worker)
        started.append(worker)

    monkeypatch.setattr(threading.Thread, "start", start)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="injected worker") as error:
            if entry == "serve":
                app.serve("127.0.0.1", port)
            else:
                app._compile()
                app._worker_process("127.0.0.1", port)
        assert app._stopping.is_set()
        assert all(not worker.is_alive() for worker in started)
        # Keep the traceback alive: garbage collection must not hide a leak.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    finally:
        app._begin_drain(timeout=0)
        for worker in started:
            worker.join(timeout=2)
        if error is not None:
            trace = error.value.__traceback__
            while trace is not None:
                for name in ("srv", "listener"):
                    value = trace.tb_frame.f_locals.get(name)
                    if isinstance(value, socket.socket):
                        with contextlib.suppress(OSError):
                            value.close()
                trace = trace.tb_next
