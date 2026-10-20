"""Direct captures are ordinary; the incumbent fallback retains its policy scope."""

import sys
from typing import Any, cast

import msgspec
import pytest

from dexpot import _plans, _preparation_policy, _response
from dexpot._plans import EndpointPlan


class Leaf(msgspec.Struct):
    value: int


@pytest.mark.parametrize(
    "restore_fails,expected", [(False, msgspec.ValidationError), (True, RuntimeError)]
)
def test_only_fallback_changes_policy_and_always_restores(monkeypatch, restore_fails, expected):
    calls = []

    class Policy:
        def current(self):
            calls.append(("current", 1))
            return 1

        def set(self, value):
            calls.append(("set", value))
            return int(restore_fails and value == 1)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False)
    monkeypatch.setattr(_plans, "compile_preparer", _response.compile_preparer)
    monkeypatch.setattr(_preparation_policy, "darwin_policy", lambda: Policy())
    endpoint = EndpointPlan("GET", "/value", lambda: None, None, list[Leaf], "", [])
    assert calls == []
    assert endpoint.encode([Leaf(1)]) == b'[{"value":1}]'
    assert calls == [], "direct capture must not issue policy RPCs"
    with pytest.raises(expected):
        endpoint.encode([Leaf(cast(Any, "bad"))])
    assert calls == [("current", 1), ("set", 0), ("set", 1)]


@pytest.mark.parametrize("previous,fail_set", [(0, False), (-1, False), (1, True)])
def test_fallback_preserves_fixed_or_unavailable_policy(monkeypatch, previous, fail_set):
    calls = []

    class Policy:
        def current(self):
            calls.append(("current", previous))
            return previous

        def set(self, value):
            calls.append(("set", value))
            return int(fail_set)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False)
    monkeypatch.setattr(_plans, "compile_preparer", _response.compile_preparer)
    monkeypatch.setattr(_preparation_policy, "darwin_policy", lambda: Policy())
    endpoint = EndpointPlan("GET", "/value", lambda: None, None, list[Leaf], "", [])
    assert endpoint.encode([{"value": 1}]) == b'[{"value":1}]'
    assert calls == (
        [("current", previous), ("set", 0)] if previous == 1 else [("current", previous)]
    )


def test_unsupported_graph_retains_its_original_outer_policy(monkeypatch):
    class Output(msgspec.Struct):
        rows: list[Leaf] = msgspec.field(default_factory=list)

    calls = []

    class Policy:
        def current(self):
            calls.append("get")
            return 1

        def set(self, value):
            calls.append(value)
            return 0

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False)
    monkeypatch.setattr(_plans, "compile_preparer", _response.compile_preparer)
    monkeypatch.setattr(_preparation_policy, "darwin_policy", lambda: Policy())
    endpoint = EndpointPlan("GET", "/value", lambda: None, None, Output, "", [])
    assert endpoint.encode(Output([])) == b'{"rows":[]}'
    assert calls == ["get", 0, 1]
