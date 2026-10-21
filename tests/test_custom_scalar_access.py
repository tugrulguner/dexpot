import msgspec

from dexpot._plans import EndpointPlan


class Custom(msgspec.Struct):
    value: str

    def __getattribute__(self, name):
        return "substituted" if name == "value" else super().__getattribute__(name)


def test_custom_access_keeps_existing_preparer():
    plan = EndpointPlan("GET", "/", lambda: None, None, Custom, "", [])
    assert not getattr(plan.resp_prepare, "__compiled_scalar__", False)
    # Runtime policy differs in baseline: graph getattr vs native Struct slots.
    from dexpot._plans import _checked_fallback, compile_preparer

    expected = msgspec.json.encode(compile_preparer(Custom, _checked_fallback)(Custom("stored")))
    assert plan.encode(Custom("stored")) == expected
