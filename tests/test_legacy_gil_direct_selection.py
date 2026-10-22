import sys
from typing import Required

import msgspec
import pytest

from dexpot import _response_legacy


class Child(msgspec.Struct):
    value: int


class Parent(msgspec.Struct):
    child: Child
    title: str


def test_gil_registration_selects_direct_with_canonical_fallback(monkeypatch):
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    original_type_info = msgspec.inspect.type_info
    inspected = []

    def count_info(annotation):
        inspected.append(annotation)
        return original_type_info(annotation)

    monkeypatch.setattr(msgspec.inspect, "type_info", count_info)
    prepare = _response_legacy.compile_preparer(Parent, lambda annotation: lambda value: value)

    assert getattr(prepare, "__direct_preparation__", False)
    assert inspected.count(Parent) == 1
    assert inspected.count(Child) == 1
    assert prepare(Parent(Child(7), "hello")) == {"child": {"value": 7}, "title": "hello"}


def test_gil_unsupported_shape_retains_canonical_callable_identity(monkeypatch):
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    def fallback(annotation):
        return lambda value: value

    prepare = _response_legacy.compile_preparer(list[int], fallback)
    assert not getattr(prepare, "__direct_preparation__", False)


def test_free_threaded_registration_retains_legacy_callable(monkeypatch):
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    prepare = _response_legacy.compile_preparer(Parent, lambda annotation: lambda value: value)
    assert not getattr(prepare, "__direct_preparation__", False)


def test_unsupported_root_retains_registration_type_error():
    with pytest.raises(TypeError, match="not supported"):
        _response_legacy.compile_preparer(Required[Parent], lambda _: lambda value: value)


def test_missing_runtime_query_selects_once_at_registration(monkeypatch):
    monkeypatch.delattr(sys, "_is_gil_enabled", raising=False)
    prepare = _response_legacy.compile_preparer(Parent, lambda _: lambda value: value)
    assert getattr(prepare, "__direct_preparation__", False)

    def forbidden():
        raise AssertionError("request path queried GIL state")

    monkeypatch.setattr(sys, "_is_gil_enabled", forbidden, raising=False)
    assert prepare(Parent(Child(7), "hello")) == {"child": {"value": 7}, "title": "hello"}


def test_unsupported_selection_returns_exact_incumbent_without_wrapper(monkeypatch):
    from dexpot import _nested_response

    captured = []
    original = _nested_response.compile_direct

    def capture(schema, incumbent, **kwargs):
        captured.append(incumbent)
        return original(schema, incumbent, **kwargs)

    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    monkeypatch.setattr(_nested_response, "compile_direct", capture)
    for schema in (int, Child, list[int]):
        returned = _response_legacy.compile_preparer(schema, lambda _: lambda value: value)
        assert returned is captured[-1]
