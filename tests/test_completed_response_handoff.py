"""Completed-response fairness handoff on bounded FT Darwin owners."""

from __future__ import annotations

import socket
import threading

from dexpot import app as app_module


def _run_owner(monkeypatch, outcomes, *, selected=True):
    app = app_module.Dex()
    app._serving_gil_free = selected
    app._response_turn_handoff = selected
    app._response_turn_cpu_budget_ns = 1_000_000 if selected else 0
    app._handoff_yield = None
    app._stopping = threading.Event()
    events = []
    calls = iter(outcomes)
    left, right = socket.socketpair()

    def process(conn, buf):
        events.append(("process", buf))
        result = next(calls)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(app, "_process", process)
    monkeypatch.setattr(app, "_handoff_yield", lambda: events.append(("yield", None)))
    try:
        app._own_connection(left, b"original")
    finally:
        left.close()
        right.close()
    return events


def test_owner_yields_only_after_cpu_budget_and_preserves_buffer(monkeypatch):
    monkeypatch.setattr(
        app_module.time,
        "thread_time_ns",
        iter((100, 400_000, 1_000_100, 1_000_200, 1_000_300)).__next__,
    )
    assert _run_owner(monkeypatch, [(True, b"one"), (True, b"pipelined"), (False, b"")]) == [
        ("process", b"original"),
        ("process", b"one"),
        ("yield", None),
        ("process", b"pipelined"),
    ]


def test_owner_accumulates_cpu_time_across_small_responses(monkeypatch):
    monkeypatch.setattr(
        app_module.time,
        "thread_time_ns",
        iter((0, 400_000, 800_000, 1_000_000, 1_000_001)).__next__,
    )
    assert _run_owner(monkeypatch, [(True, b"a"), (True, b"b"), (True, b"c"), (False, b"")]) == [
        ("process", b"original"),
        ("process", b"a"),
        ("process", b"b"),
        ("yield", None),
        ("process", b"c"),
    ]


def test_owner_uses_thread_cpu_not_wall_clock(monkeypatch):
    monkeypatch.setattr(app_module.time, "thread_time_ns", iter((10, 20, 30)).__next__)
    monkeypatch.setattr(
        app_module.time,
        "monotonic",
        lambda: (_ for _ in ()).throw(AssertionError("wall clock used")),
    )
    assert _run_owner(monkeypatch, [(True, b"next"), (False, b"")]) == [
        ("process", b"original"),
        ("process", b"next"),
    ]


def test_owner_does_not_yield_after_close(monkeypatch):
    assert _run_owner(monkeypatch, [(False, b"")]) == [("process", b"original")]


def test_owner_does_not_yield_when_processing_fails(monkeypatch):
    assert _run_owner(monkeypatch, [OSError("failed")]) == [("process", b"original")]


def test_owner_does_not_sample_cpu_after_close_or_processing_error(monkeypatch):
    samples = iter((0,))
    monkeypatch.setattr(app_module.time, "thread_time_ns", lambda: next(samples))
    assert _run_owner(monkeypatch, [(False, b"")]) == [("process", b"original")]
    samples = iter((0,))
    monkeypatch.setattr(app_module.time, "thread_time_ns", lambda: next(samples))
    assert _run_owner(monkeypatch, [OSError("failed")]) == [("process", b"original")]


def test_unselected_owner_does_not_read_cpu_clock(monkeypatch):
    monkeypatch.setattr(
        app_module.time,
        "thread_time_ns",
        lambda: (_ for _ in ()).throw(AssertionError("CPU clock used")),
    )
    assert _run_owner(monkeypatch, [(True, b"next"), (False, b"")], selected=False) == [
        ("process", b"original"),
        ("process", b"next"),
    ]


def test_handoff_selection_is_bound_from_runtime_platform_and_gil(monkeypatch):
    monkeypatch.setattr(app_module, "_FT_CONNECTION_SLOTS", None)
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.os, "sched_yield", lambda: None, raising=False)
    app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    app._bind_runtime()
    assert app._runtime_info()["response_turn_handoff"] is True
    assert app._runtime_info()["response_turn_cpu_budget_ns"] == 1_000_000

    gil_app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: True, raising=False)
    gil_app._bind_runtime()
    assert gil_app._runtime_info()["response_turn_handoff"] is False
    assert gil_app._runtime_info()["response_turn_cpu_budget_ns"] == 0

    linux_app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    linux_app._bind_runtime()
    assert linux_app._runtime_info()["response_turn_handoff"] is False


def test_unselected_owner_preserves_loop_without_yield(monkeypatch):
    assert _run_owner(monkeypatch, [(True, b"next"), (False, b"")], selected=False) == [
        ("process", b"original"),
        ("process", b"next"),
    ]


def test_missing_scheduler_yield_keeps_handoff_disabled(monkeypatch):
    monkeypatch.setattr(app_module, "_FT_CONNECTION_SLOTS", None)
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    monkeypatch.delattr(app_module.os, "sched_yield", raising=False)
    app = app_module.Dex()
    app._bind_runtime()
    assert app._runtime_info()["response_turn_handoff"] is False


def test_bound_handoff_does_not_repeat_runtime_selection(monkeypatch):
    monkeypatch.setattr(app_module, "_FT_CONNECTION_SLOTS", None)
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.os, "sched_yield", lambda: None, raising=False)
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    app = app_module.Dex()
    app._bind_runtime()
    selected = app._handoff_yield

    def unexpected_query():
        raise AssertionError("runtime selection repeated")

    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", unexpected_query)
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    app._bind_runtime()
    assert app._handoff_yield is selected
    assert app._response_turn_handoff is True
