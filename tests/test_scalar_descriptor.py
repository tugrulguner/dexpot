from typing import Any, cast

import msgspec

from dexpot._plans import EndpointPlan, _checked_fallback, compile_preparer


def test_descriptor_replacement_returns_to_incumbent():
    class Value(msgspec.Struct):
        x: int

    plan = EndpointPlan("GET", "/", lambda: None, None, Value, "", [])
    old = compile_preparer(Value, _checked_fallback)
    item = Value(4)
    cast(Any, Value).x = property(lambda self: 99)
    assert plan.encode(item) == msgspec.json.encode(old(item))
