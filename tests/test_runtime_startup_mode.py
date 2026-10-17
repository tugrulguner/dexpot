"""Bind serving policy after application loading; report later mode changes."""

import logging
import os
import socket
import sys

import pytest

from dexpot import Dex
from dexpot import app as module


class StopBeforeListen(Exception):
    pass


def test_serve_binds_current_mode_before_compiling_application(monkeypatch):
    app = Dex()
    # Model an application import enabling the GIL after dexpot was imported.
    monkeypatch.setattr(module, "_gil_free", True)
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    observed = []

    def compile_application():
        observed.append(app._runtime_info())
        raise StopBeforeListen

    monkeypatch.setattr(app, "_compile", compile_application)
    with pytest.raises(StopBeforeListen):
        app.serve()
    assert observed[0]["selected_gil_enabled"] is True
    assert observed[0]["execution_mode"] == "pooled-gil"
    assert observed[0]["pid"] == os.getpid()


@pytest.mark.parametrize("free_threaded_build", [False, True])
def test_runtime_diagnostics_distinguish_build_from_gil_state(monkeypatch, free_threaded_build):
    monkeypatch.setattr(module.sysconfig, "get_config_var", lambda key: int(free_threaded_build))
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    app = Dex()
    app._bind_runtime()
    info = app._runtime_info()
    assert info["free_threaded_build"] is free_threaded_build
    assert info["gil_enabled"] is True
    assert info["selected_gil_enabled"] is True
    assert info["execution_mode"] == "pooled-gil"
    description = app._runtime_description()
    assert "GIL enabled" in description
    assert ("free-threaded Python" in description) is free_threaded_build


def test_mode_change_is_reported_once_without_rebinding_execution(monkeypatch, caplog):
    enabled = [False]
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: enabled[0], raising=False)
    monkeypatch.setattr(module, "_FT_CONNECTION_SLOTS", None)
    app = Dex()
    app._bind_runtime()
    enabled[0] = True
    with caplog.at_level(logging.WARNING, logger="dexpot.error"):
        app._check_runtime_mode()
        app._check_runtime_mode()
    messages = [record.message for record in caplog.records if "GIL" in record.message]
    assert len(messages) == 1
    assert "changed" in messages[0]
    info = app._runtime_info()
    assert info["gil_enabled"] is True
    assert info["selected_gil_enabled"] is False
    assert info["execution_mode"] == "bounded-ft"


def test_admission_does_not_query_gil_state_per_request(monkeypatch):
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    app = Dex()
    app._bind_runtime()
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: pytest.fail("hot-path GIL query"))
    server, client = socket.socketpair()
    try:
        app._handle_admission(server, b"")
        assert len(app._work) == 1
    finally:
        app._work.clear()
        server.close()
        client.close()


def test_bound_free_threaded_apps_share_process_connection_budget(monkeypatch):
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False, raising=False)
    monkeypatch.setattr(module, "_FT_CONNECTION_SLOTS", None)
    first, second = Dex(), Dex()
    first._bind_runtime()
    slots = module._FT_CONNECTION_SLOTS
    second._bind_runtime()
    assert slots is not None
    assert module._FT_CONNECTION_SLOTS is slots
    assert first._runtime_info()["selected_gil_enabled"] is False
    assert second._runtime_info()["selected_gil_enabled"] is False


def test_older_interpreter_without_gil_query_binds_gil_mode(monkeypatch):
    monkeypatch.delattr(sys, "_is_gil_enabled", raising=False)
    app = Dex()
    app._bind_runtime()
    assert app._runtime_info()["selected_gil_enabled"] is True


def test_automatic_pool_defaults_follow_startup_not_import_mode(monkeypatch):
    monkeypatch.setattr(module, "_gil_free", True)
    monkeypatch.setattr(module, "_POOL_AUTOMATIC", True, raising=False)
    monkeypatch.setattr(module, "_QUEUE_AUTOMATIC", True, raising=False)
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    app = Dex()
    app._bind_runtime()
    info = app._runtime_info()
    assert info["pool_size"] == module._cores * 2 + 2
    assert info["max_queue"] == info["pool_size"] * 2
