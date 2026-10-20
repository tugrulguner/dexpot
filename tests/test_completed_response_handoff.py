"""Completed-response fairness handoff on bounded FT Darwin owners."""

from __future__ import annotations

import socket
import threading

from dexpot import app as app_module


def _run_owner(monkeypatch, outcomes, *, selected=True):
    app = app_module.Dex()
    app._serving_gil_free = selected
    app._response_turn_handoff = selected
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


def test_owner_yields_after_completed_keepalive_and_preserves_buffer(monkeypatch):
    assert _run_owner(monkeypatch, [(True, b"pipelined"), (False, b"")]) == [
        ("process", b"original"),
        ("yield", None),
        ("process", b"pipelined"),
    ]


def test_owner_does_not_yield_after_close(monkeypatch):
    assert _run_owner(monkeypatch, [(False, b"")]) == [("process", b"original")]


def test_owner_does_not_yield_when_processing_fails(monkeypatch):
    assert _run_owner(monkeypatch, [OSError("failed")]) == [("process", b"original")]


def test_handoff_selection_is_bound_from_runtime_platform_and_gil(monkeypatch):
    monkeypatch.setattr(app_module, "_FT_CONNECTION_SLOTS", None)
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.os, "sched_yield", lambda: None, raising=False)
    app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    app._bind_runtime()
    assert app._runtime_info()["response_turn_handoff"] is True

    gil_app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: True, raising=False)
    gil_app._bind_runtime()
    assert gil_app._runtime_info()["response_turn_handoff"] is False

    linux_app = app_module.Dex()
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(app_module.sys, "_is_gil_enabled", lambda: False, raising=False)
    linux_app._bind_runtime()
    assert linux_app._runtime_info()["response_turn_handoff"] is False
