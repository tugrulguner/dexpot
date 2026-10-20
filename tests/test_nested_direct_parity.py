"""Compare direct projection against the actual selected endpoint incumbent."""

import json
import math
import sys
from typing import Annotated, Any, cast

import msgspec
import pytest

from dexpot import _response
from dexpot._nested_response import compile_direct
from dexpot._plans import EndpointPlan
from dexpot.requests import Request


class Dimensions(msgspec.Struct, frozen=True):
    width: int
    height: int


class Details(msgspec.Struct, frozen=True):
    category: str
    dimensions: Dimensions


class Item(msgspec.Struct, frozen=True):
    id: int
    name: str
    details: Details


class Private(Item, frozen=True):
    private: Any


class Numeric(msgspec.Struct):
    value: float


class Constrained(msgspec.Struct):
    value: Annotated[int, msgspec.Meta(ge=1)]


class ListConstrained(msgspec.Struct):
    rows: Annotated[list[Dimensions], msgspec.Meta(min_length=2)]


class Recursive(msgspec.Struct):
    children: list["Recursive"]


def plan(schema):
    from dexpot._plans import _checked_fallback

    endpoint = EndpointPlan("GET", "/value", lambda: None, None, schema, "", [])
    # These collection contracts used the graph before the new selector. Keep
    # that literal incumbent as the oracle, even on an optimized FT host.
    original = _response.compile_binding(schema, _checked_fallback).canonical
    object.__setattr__(endpoint, "resp_prepare", original)
    return endpoint


def context():
    return Request("GET", "/private", {}, "", {})


def outcome(endpoint, value):
    try:
        return "ok", endpoint.encode(value)
    except Exception as error:
        return "error", type(error).__name__


@pytest.mark.parametrize(
    "schema,make,error",
    [
        (list[Numeric], lambda: [Numeric(math.nan)], True),
        (list[Numeric], lambda: [Numeric(math.inf)], True),
        (list[Numeric], lambda: [Numeric(cast(Any, 2))], False),
        (list[Numeric], lambda: [Numeric(cast(Any, 10**400))], True),
        (list[Constrained], lambda: [Constrained(-1)], True),
        (list[Constrained], lambda: [Constrained(3)], False),
        (list[Item], lambda: [Item(cast(Any, True), "x", Details("d", Dimensions(2, 3)))], True),
        (list[Item], lambda: [Item(1, "x", Details("d", Dimensions(cast(Any, "bad"), 3)))], True),
        (list[Item], lambda: [Item(1, cast(Any, context()), Details("d", Dimensions(2, 3)))], True),
        (list[Item], lambda: [Private(1, "x", Details("d", Dimensions(2, 3)), context())], True),
        (list[Item], lambda: [Private(1, "x", Details("d", Dimensions(2, 3)), "discarded")], False),
    ],
)
def test_direct_values_match_the_selected_endpoint(schema, make, error):
    baseline = plan(schema)
    expected = outcome(baseline, make())
    assert (expected[0] == "error") is error
    candidate = plan(schema)
    direct, supported = compile_direct(schema, candidate.resp_prepare)
    if supported:
        assert direct is not None
        object.__setattr__(candidate, "resp_prepare", direct())
    assert outcome(candidate, make()) == expected


@pytest.mark.parametrize(
    "schema",
    [Annotated[list[Item], msgspec.Meta(min_length=2)], ListConstrained, Recursive],
)
def test_constrained_and_recursive_contracts_retain_the_incumbent(schema):
    direct, supported = compile_direct(schema, lambda value: value)
    assert direct is None and not supported


def test_deleted_slot_returns_to_the_incumbent():
    value = [Item(1, "x", Details("d", Dimensions(2, 3)))]
    msgspec.structs.force_setattr(value[0].details, "dimensions", Dimensions(2, 3))
    # Use the non-frozen test shape to delete an actual stored slot.
    from test_nested_direct import Leaf

    leaf = Leaf(3)
    del leaf.value
    baseline = plan(list[Leaf])
    expected = outcome(baseline, [leaf])
    assert expected[0] == "error"
    candidate = plan(list[Leaf])
    direct, supported = compile_direct(list[Leaf], candidate.resp_prepare)
    assert supported and direct is not None
    object.__setattr__(candidate, "resp_prepare", direct())
    assert outcome(candidate, [leaf]) == expected


def test_frozen_infos_are_not_reinspected_during_binding(monkeypatch):
    endpoint = plan(list[Item])
    binding = _response.compile_binding(list[Item], lambda _: endpoint.resp_prepare)
    direct, supported = compile_direct(list[Item], endpoint.resp_prepare, infos=binding.infos)
    assert supported and direct is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("worker-time inspection")

    monkeypatch.setattr(msgspec.inspect, "type_info", forbidden)
    prepared = direct()
    result = prepared([Item(1, "x", Details("d", Dimensions(2, 3)))])
    assert json.loads(msgspec.json.encode(result))[0]["id"] == 1


def test_gil_or_linux_binding_keeps_the_owned_graph(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    endpoint = plan(list[Item])
    binding = _response.compile_binding(list[Item], lambda _: endpoint.resp_prepare)
    assert binding.direct_factory is None
    assert not getattr(binding.bind(), "__direct_preparation__", False)
