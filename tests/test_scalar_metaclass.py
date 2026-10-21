"""A scalar candidate must not add observable metaclass field lookups."""

import msgspec

from dexpot._plans import EndpointPlan, _checked_fallback, compile_preparer


def test_custom_metaclass_keeps_incumbent_without_extra_field_lookup():
    armed = False

    class Meta(type(msgspec.Struct)):
        def __getattribute__(cls, name):
            if armed and name == "value":
                raise RuntimeError("unexpected class field lookup")
            return super().__getattribute__(name)

    class Payload(msgspec.Struct, metaclass=Meta):
        value: int

    incumbent = compile_preparer(Payload, _checked_fallback)
    plan = EndpointPlan("GET", "/", lambda: None, None, Payload, "", [])
    value = Payload(7)
    armed = True
    expected = msgspec.json.encode(incumbent(value))
    assert plan.encode(value) == expected == b'{"value":7}'
    assert not getattr(plan.resp_prepare, "__compiled_scalar__", False)
