from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "outbound_under_test", ROOT / "examples/outbound_io.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_outbound_guidance_links_the_runnable_application_example():
    for relative in (
        "README.md",
        "examples/README.md",
        "website/src/content/docs/route-contract.md",
        "src/dexpot/templates/skills/dexpot.md",
    ):
        assert "outbound_io.py" in (ROOT / relative).read_text(), relative


def test_upstream_listener_closes_when_thread_construction_fails(example, monkeypatch):
    listeners = []
    original = example.LocalServer

    class TrackedServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            listeners.append(self)

    def fail_thread(*args, **kwargs):
        raise RuntimeError("thread construction failed")

    monkeypatch.setattr(example, "LocalServer", TrackedServer)
    monkeypatch.setattr(example, "threading", types.SimpleNamespace(Thread=fail_thread))
    try:
        with pytest.raises(RuntimeError, match="thread construction failed"), example.resources():
            pytest.fail("startup unexpectedly succeeded")
        assert len(listeners) == 1
        assert listeners[0].socket.fileno() == -1, "failed acquisition must close the real listener"
        assert example.state == {}
    finally:
        for listener in listeners:
            listener.server_close()


def test_malformed_reply_discards_the_leased_connection(example):
    with example.resources():
        previous = example.state["pool"]._available[0]
        with pytest.raises(example.HTTPError) as failure:
            example._fetch("/malformed")
        assert failure.value.status == 502
        assert example.state["pool"]._available[0] is not previous
        assert example._fetch("/ok") == (200, {"message": "local upstream"})


def test_upstream_listener_closes_when_thread_start_fails(example, monkeypatch):
    listeners = []
    original = example.LocalServer

    class TrackedServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            listeners.append(self)

        def shutdown(self):
            raise AssertionError("must not wait on an unstarted upstream")

    class FailedThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(example, "LocalServer", TrackedServer)
    monkeypatch.setattr(example, "threading", types.SimpleNamespace(Thread=FailedThread))
    try:
        with pytest.raises(RuntimeError, match="thread start failed"), example.resources():
            pytest.fail("startup unexpectedly succeeded")
        assert listeners[0].socket.fileno() == -1
        assert example.state == {}
    finally:
        for listener in listeners:
            listener.server_close()


def test_pool_acquisition_failure_stops_real_upstream_and_listener(example, monkeypatch):
    listeners, threads = [], []
    original = example.LocalServer

    class TrackedServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            listeners.append(self)

    def startable_thread(*args, **kwargs):
        thread = threading.Thread(*args, **kwargs)
        threads.append(thread)
        return thread

    def fail_pool(*args, **kwargs):
        raise RuntimeError("pool allocation failed")

    monkeypatch.setattr(example, "LocalServer", TrackedServer)
    monkeypatch.setattr(example, "threading", types.SimpleNamespace(Thread=startable_thread))
    monkeypatch.setattr(example, "OutboundPool", fail_pool)
    with pytest.raises(RuntimeError, match="pool allocation failed"), example.resources():
        pytest.fail("startup unexpectedly succeeded")
    assert len(threads) == 1 and not threads[0].is_alive()
    assert listeners[0].socket.fileno() == -1
    assert example.state == {}


def test_exclusive_pool_and_normal_cleanup_release_all_resources(example):
    with example.resources():
        pool = example.state["pool"]
        with pool.lease() as connection:
            with pytest.raises(example.HTTPError) as failure:
                example._fetch("/ok")
            assert failure.value.status == 503
            assert pool._available == []
        assert pool._available == [connection]
        assert example._fetch("/ok") == (200, {"message": "local upstream"})
    assert pool._available == [] and example.state == {}


def test_timeout_replaces_connection_then_recovers_when_upstream_finishes(example, monkeypatch):
    completed = threading.Event()
    original = example.LocalHandler.do_GET

    def observed(handler):
        try:
            original(handler)
        finally:
            if handler.path == "/slow":
                completed.set()

    monkeypatch.setattr(example.LocalHandler, "do_GET", observed)
    with example.resources():
        previous = example.state["pool"]._available[0]
        with pytest.raises(example.HTTPError) as failure:
            example._fetch("/slow")
        assert failure.value.status == 504
        assert example.state["pool"]._available[0] is not previous
        assert completed.wait(timeout=2), "socket timeout does not cancel fixture work"
        assert example._fetch("/ok") == (200, {"message": "local upstream"})


def test_oversized_upstream_body_is_rejected_and_connection_replaced(example):
    with example.resources():
        previous = example.state["pool"]._available[0]
        with pytest.raises(example.HTTPError) as failure:
            example._fetch("/oversized")
        assert failure.value.status == 502
        assert failure.value.detail == "upstream unavailable"
        assert example.state["pool"]._available[0] is not previous
        assert example._fetch("/ok") == (200, {"message": "local upstream"})
