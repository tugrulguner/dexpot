import msgspec

from dexpot._plans import EndpointPlan, _checked_fallback, compile_preparer


def test_unset_slot_with_custom_getattr_preserves_incumbent():
    class Model(msgspec.Struct):
        x: int

        def __getattr__(self, name):
            if name == "x":
                return 99
            raise AttributeError(name)

    value = Model(4)
    del value.x
    original = compile_preparer(Model, _checked_fallback)
    plan = EndpointPlan("GET", "/", lambda: None, None, Model, "", [])
    try:
        expected = msgspec.json.encode(original(value))
    except Exception as exc:
        try:
            plan.encode(value)
        except Exception as actual:
            assert type(actual) is type(exc)
        else:
            raise AssertionError("candidate accepted an incumbent-invalid unset slot")
    else:
        assert plan.encode(value) == expected
