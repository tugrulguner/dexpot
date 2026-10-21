"""Keep already-selected graph preparation outside the scalar experiment."""

import msgspec

from dexpot import _plans


def test_graph_incumbent_is_retained_without_a_scalar_wrapper(monkeypatch):
    class Payload(msgspec.Struct):
        value: int

    # Exercise the registration/compiler boundary independently of the OS policy.
    # This ordinary callable models the graph incumbent, not the private native
    # whole-codec marker that the experiment is intended to replace.
    def graph(value):
        return {"value": value.value}

    def select_graph(schema, fallback):
        assert schema is Payload
        assert fallback is _plans._checked_fallback
        return graph

    monkeypatch.setattr(_plans, "compile_preparer", select_graph)
    plan = _plans.EndpointPlan("GET", "/", lambda: None, None, Payload, "", [])
    assert plan.resp_prepare is graph
    assert plan.encode(Payload(7)) == b'{"value":7}'
