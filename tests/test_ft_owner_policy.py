import socket
import threading
from typing import cast

import pytest

from dexpot import _preparation_policy
from dexpot import app as app_module
from dexpot.app import Dex


class FakePolicy:
    def __init__(self, current, set_results=()):
        self.value = current
        self.set_results = iter(set_results)
        self.calls = []

    def current(self):
        self.calls.append(("current", threading.get_ident(), self.value))
        return self.value

    def set(self, value):
        result = next(self.set_results, 0)
        self.calls.append(("set", threading.get_ident(), value, result))
        if result == 0:
            self.value = value
        return result


def app_with_policy(monkeypatch, policy):
    monkeypatch.setattr(_preparation_policy, "darwin_policy", lambda: policy)
    monkeypatch.setattr(app_module, "darwin_policy", lambda: policy)
    monkeypatch.setattr(app_module, "_FT_CONNECTION_SLOTS", None)
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        app_module,
        "sys",
        type(
            "FakeSys",
            (),
            {
                "platform": "darwin",
                "_is_gil_enabled": staticmethod(lambda: False),
                "version": "test",
            },
        )(),
    )
    app = Dex()
    app._bind_runtime()
    return app


def test_ft_worker_enters_fixed_policy_and_restores_before_exit(monkeypatch):
    policy = FakePolicy(1)
    app = app_with_policy(monkeypatch, policy)
    seen = []
    app._own_connection = lambda *a, **kw: seen.append((policy.value, kw["registered"]))
    app._own_connection_ft(cast(socket.socket, object()), b"")
    assert seen == [(0, True)]
    assert [call[0] for call in policy.calls] == ["current", "set", "set"]
    assert policy.value == 1


def test_ft_worker_preserves_policy_failure_and_already_fixed(monkeypatch):
    unavailable = FakePolicy(-1)
    app = app_with_policy(monkeypatch, unavailable)
    seen = []
    app._own_connection = lambda *a, **kw: seen.append(unavailable.value)
    app._own_connection_ft(cast(socket.socket, object()), b"")
    assert seen == [-1]
    assert [call[0] for call in unavailable.calls] == ["current"]

    fixed = FakePolicy(0)
    app = app_with_policy(monkeypatch, fixed)
    app._own_connection = lambda *a, **kw: None
    app._own_connection_ft(cast(socket.socket, object()), b"")
    assert [call[0] for call in fixed.calls] == ["current"]


def test_ft_worker_falls_back_when_initial_set_fails(monkeypatch):
    policy = FakePolicy(1, [5])
    app = app_with_policy(monkeypatch, policy)
    seen = []
    app._own_connection = lambda *a, **kw: seen.append(policy.value)
    app._own_connection_ft(cast(socket.socket, object()), b"")
    assert seen == [1]
    assert [call[0] for call in policy.calls] == ["current", "set"]


def test_ft_worker_restores_on_handler_error_and_reports_restore_failure(monkeypatch):
    policy = FakePolicy(1)
    app = app_with_policy(monkeypatch, policy)
    app._own_connection = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("handler"))
    with pytest.raises(RuntimeError, match="handler"):
        app._own_connection_ft(cast(socket.socket, object()), b"")
    assert policy.value == 1

    policy = FakePolicy(1, [0, 9])
    app = app_with_policy(monkeypatch, policy)
    app._own_connection = lambda *a, **kw: None
    with pytest.raises(RuntimeError, match="restore"):
        app._own_connection_ft(cast(socket.socket, object()), b"")


def test_owner_policy_selection_is_startup_diagnostic_only(monkeypatch):
    policy = FakePolicy(1)
    app = app_with_policy(monkeypatch, policy)
    assert app._runtime_info()["response_owner_policy_selected"] is True
    assert policy.calls == []
