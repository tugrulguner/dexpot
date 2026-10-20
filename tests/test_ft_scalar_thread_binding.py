from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, cast

import msgspec
import pytest

from dexpot._plans import (
    EndpointPlan,
    _checked_fallback,
    _NativeCheckedPreparation,
    compile_preparer,
)
from dexpot._scalar_response import compile_scalar


class Payload(msgspec.Struct):
    value: int


def test_ft_binder_owns_a_distinct_function_and_globals_per_thread():
    if getattr(__import__("sys"), "_is_gil_enabled", lambda: True)():
        pytest.skip("FT-only strategy")
    prepare = compile_scalar(Payload, lambda value: {"fallback": value})
    value = Payload(7)

    barrier = Barrier(2)

    def bind_and_inspect(_):
        prepare(value)
        barrier.wait()
        assert prepare.__closure__ is not None
        local = next(
            cell.cell_contents
            for cell in prepare.__closure__
            if hasattr(cell.cell_contents, "prepare")
        )
        function = local.prepare
        return function, function.__globals__

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(bind_and_inspect, range(2)))

    assert first[0] is not second[0]
    assert first[1] is not second[1]
    assert first[0].__code__ is second[0].__code__
    assert first[0](value) == {"value": 7}
    assert second[0](value) == {"value": 7}


def test_endpoint_plan_uses_thread_owned_scalar_projection():
    if getattr(__import__("sys"), "_is_gil_enabled", lambda: True)():
        pytest.skip("FT-only strategy")
    plan = EndpointPlan("GET", "/", lambda: None, None, Payload, "", [])
    native = isinstance(compile_preparer(Payload, _checked_fallback), _NativeCheckedPreparation)
    assert bool(getattr(plan.resp_prepare, "__compiled_scalar__", False)) is native
    assert plan.encode(Payload(11)) == b'{"value":11}'


def test_ineligible_schema_retains_exact_fallback():
    class Ineligible(msgspec.Struct):
        value: int = 0

    sentinel = object()
    calls = []

    def fallback(value):
        calls.append(value)
        return sentinel

    prepare = compile_scalar(Ineligible, fallback)
    value = Ineligible()
    assert prepare is fallback
    assert prepare(value) is sentinel
    assert calls == [value]


def test_descriptor_rebinding_and_custom_access_guard_use_fallback():
    if getattr(__import__("sys"), "_is_gil_enabled", lambda: True)():
        pytest.skip("FT-only strategy")

    class Mutable(msgspec.Struct):
        value: int

    fallback_calls = []

    def fallback(value):
        fallback_calls.append(value)
        return {"fallback": True}

    prepare = compile_scalar(Mutable, fallback)
    value = Mutable(3)
    assert prepare(value) == {"value": 3}
    cast(Any, Mutable).value = property(lambda self: 8)
    assert prepare(value) == {"fallback": True}
    assert fallback_calls == [value]

    class Custom(msgspec.Struct):
        item: int

        def __getattribute__(self, name):
            if name == "item":
                return 99
            return super().__getattribute__(name)

    def custom_fallback(item):
        return {"incumbent": item.item}

    custom = compile_scalar(Custom, custom_fallback)
    item = Custom(1)
    assert custom is custom_fallback
    assert custom(item) == {"incumbent": 99}
