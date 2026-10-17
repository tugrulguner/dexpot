import msgspec
import pytest

from dexpot._plans import EndpointPlan


class Item(msgspec.Struct):
    id: int
    name: str
    price: float


@pytest.mark.skipif(
    getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(), reason="FT-only strategy"
)
def test_compiled_path_is_selected_and_avoids_native_roundtrip(monkeypatch):
    plan = EndpointPlan("GET", "/", lambda: None, None, Item, "", [])
    assert getattr(plan.resp_prepare, "__compiled_scalar__", False)

    def forbidden(*a, **kw):
        raise AssertionError("native conversion called")

    monkeypatch.setattr(msgspec, "to_builtins", forbidden)
    monkeypatch.setattr(msgspec, "convert", forbidden)
    assert plan.encode(Item(7, "item-7", 9.99)) == b'{"id":7,"name":"item-7","price":9.99}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_never_becomes_valid_null(value):
    plan = EndpointPlan("GET", "/", lambda: None, None, Item, "", [])
    with pytest.raises((TypeError, ValueError)):
        plan.encode(Item(7, "x", value))
