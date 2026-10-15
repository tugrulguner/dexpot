import msgspec
import pytest

from dexpot._plans import EndpointPlan


def test_flat_compiled_response_is_used_by_endpoint_and_rejects_malformed_values():
    class Payload(msgspec.Struct):
        name: str
        count: int

    plan = EndpointPlan("GET", "/", lambda: None, None, Payload, "", [])
    assert plan.encode(Payload("x", 3)) == b'{"name":"x","count":3}'
    malformed = Payload("x", 3)
    msgspec.structs.force_setattr(malformed, "count", True)
    with pytest.raises((TypeError, ValueError, msgspec.ValidationError)):
        plan.encode(malformed)
