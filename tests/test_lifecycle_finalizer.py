from __future__ import annotations

import contextlib
import threading

import pytest

from dexpot import Dex


def test_completion_before_waiter_runs_still_releases_resource(monkeypatch) -> None:
    app = Dex()
    closed = threading.Event()
    waiter_started = threading.Event()
    allow_waiter = threading.Event()

    @contextlib.contextmanager
    def resource():
        try:
            yield
        finally:
            closed.set()

    app.lifespan(resource)
    state = app._lifecycle
    original_thread = threading.Thread

    class DelayedWaiter(original_thread):
        def run(self) -> None:
            waiter_started.set()
            assert allow_waiter.wait(3)
            super().run()

    monkeypatch.setattr(threading, "Thread", DelayedWaiter)
    marker = object()
    try:
        with state._acquire_lifecycle(), app._cond:
            app._active_connections.add(marker)  # type: ignore[arg-type]
        assert waiter_started.wait(3)
        waiter = state._finalizer
        with app._cond:
            app._active_connections.clear()
            app._cond.notify_all()
        assert not closed.is_set()
        allow_waiter.set()
        assert closed.wait(3)
        assert waiter is not None
        waiter.join(3)
        assert not waiter.is_alive()
    finally:
        allow_waiter.set()
        with app._cond:
            app._active_connections.clear()
            app._cond.notify_all()


def test_deferred_cleanup_error_is_visible_and_does_not_skip_other_exits(caplog) -> None:
    app = Dex()
    events: list[str] = []

    @contextlib.contextmanager
    def resource(name: str, fails: bool):
        try:
            yield
        finally:
            events.append(name)
            if fails:
                raise RuntimeError("cleanup sentinel")

    app.lifespan(lambda: resource("first", False))
    app.lifespan(lambda: resource("second", True))
    state = app._lifecycle
    with state._acquire_lifecycle(), app._cond:
        app._active_connections.add(object())  # type: ignore[arg-type]
    waiter = state._finalizer
    with app._cond:
        app._active_connections.clear()
        app._cond.notify_all()
    assert waiter is not None
    waiter.join(3)
    assert not waiter.is_alive()
    assert events == ["second", "first"]
    assert len(state.cleanup_errors) == 1
    assert isinstance(state.cleanup_errors[0], RuntimeError)
    assert "cleanup sentinel" in caplog.text
    state._release_deferred_lifecycle()
    assert events == ["second", "first"]


def test_registration_and_normal_scope_do_not_start_finalizer(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("normal lifecycle operation started a finalizer")

    monkeypatch.setattr(threading, "Thread", forbidden)
    app = Dex()
    app.lifespan(contextlib.nullcontext)
    with app._lifecycle._acquire_lifecycle():
        pass
    assert app._lifecycle._finalizer is None


def test_registration_is_frozen_after_compile() -> None:
    app = Dex()
    app._compile()
    with pytest.raises(RuntimeError, match="frozen"):
        app.lifespan(contextlib.nullcontext)


def test_drain_joins_real_application_owners_not_control_plane(monkeypatch) -> None:
    import dexpot._lifecycle as lifecycle_module
    import dexpot.app as app_module

    app = Dex()
    app.lifespan(contextlib.nullcontext)
    target_finished = threading.Event()
    release_thread = threading.Event()
    join_entered = threading.Event()

    class HeldOwner(threading.Thread):
        def run(self) -> None:
            super().run()
            target_finished.set()
            assert release_thread.wait(3)

        def join(self, timeout=None) -> None:
            join_entered.set()
            super().join(timeout)

    owner = HeldOwner(target=lambda: None)
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    registry = {owner: (app, slots)}
    monkeypatch.setattr(app_module, "_FT_OWNERS", registry)
    monkeypatch.setattr(lifecycle_module, "_FT_OWNERS", registry)
    owner.start()
    drain = threading.Thread(target=lambda: app._lifecycle._begin_drain(timeout=2))
    try:
        assert target_finished.wait(2)
        drain.start()
        assert join_entered.wait(1), "drain skipped the application's native owner thread"
        assert not slots.acquire(blocking=False)
        release_thread.set()
        drain.join(3)
        assert not drain.is_alive()
        assert not registry
        assert slots.acquire(blocking=False)
    finally:
        release_thread.set()
        owner.join(3)
        if drain.ident is not None:
            drain.join(3)
