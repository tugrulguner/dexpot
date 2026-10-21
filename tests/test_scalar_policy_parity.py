"""Compare scalar output with the actual runtime-selected incumbent codec."""

import sys

import msgspec
import pytest

from dexpot._plans import EndpointPlan, _checked_fallback, compile_preparer


def plans(schema):
    candidate = EndpointPlan("GET", "/", lambda: None, None, schema, "", [])
    incumbent = EndpointPlan("GET", "/", lambda: None, None, schema, "", [])
    object.__setattr__(incumbent, "resp_prepare", compile_preparer(schema, _checked_fallback))
    return incumbent, candidate


def outcome(plan, value):
    try:
        return "bytes", plan.encode(value)
    except Exception as exc:
        # Private traceback/message wording is not a public wire contract.
        return "error", type(exc)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"rename": "camel"},
        {"rename": {"item_id": "public-字段", "display_name": "display-name"}},
        {"omit_defaults": True},
        {"forbid_unknown_fields": True},
        {"frozen": True, "gc": False},
        {"kw_only": True},
        {"weakref": True},
        {"array_like": True},
        {"dict": True},
        {"tag": True},
        {"tag": "demo", "tag_field": "kind"},
    ],
)
def test_struct_configuration_matches_selected_incumbent(config):
    schema = msgspec.defstruct(
        "ScalarParity",
        [
            ("item_id", int),
            ("display_name", str),
            ("price", float),
            ("ready", bool),
            ("empty", type(None)),
        ],
        **config,
    )
    value = schema(item_id=7, display_name='é\nquoted"', price=9.99, ready=True, empty=None)
    incumbent, candidate = plans(schema)
    assert outcome(candidate, value) == outcome(incumbent, value)
    assert outcome(candidate, value)[0] == "bytes"


@pytest.mark.parametrize(
    "case", ["mapping", "private_subtype", "bool_id", "integer_float", "nonfinite", "unset"]
)
def test_fallback_values_match_selected_incumbent(case):
    class Payload(msgspec.Struct):
        item_id: int
        price: float

    class Private(Payload):
        private: str

    value = Payload(7, 9.99)
    if case == "mapping":
        value = {"item_id": 7, "price": 9.99, "private": "omit-me"}
    elif case == "private_subtype":
        value = Private(7, 9.99, "omit-me")
    elif case == "bool_id":
        msgspec.structs.force_setattr(value, "item_id", True)
    elif case == "integer_float":
        msgspec.structs.force_setattr(value, "price", 9)
    elif case == "nonfinite":
        msgspec.structs.force_setattr(value, "price", float("inf"))
    else:
        del value.item_id
    incumbent, candidate = plans(Payload)
    assert outcome(candidate, value) == outcome(incumbent, value)


def test_registered_strategy_does_not_poll_gil_during_encoding(monkeypatch):
    class Payload(msgspec.Struct):
        item_id: int

    plan = EndpointPlan("GET", "/", lambda: None, None, Payload, "", [])
    selected = plan.resp_prepare

    # Existing tests can leave owned server threads active. Observe only the
    # encoding thread, not their legitimate accept-loop diagnostics.
    import threading

    encoding_thread = threading.get_ident()
    actual_query = getattr(sys, "_is_gil_enabled", lambda: True)

    def forbidden():
        if threading.get_ident() == encoding_thread:
            raise AssertionError("request-path GIL query")
        return actual_query()

    monkeypatch.setattr(sys, "_is_gil_enabled", forbidden, raising=False)
    assert plan.encode(Payload(7)) == b'{"item_id":7}'
    assert plan.resp_prepare is selected
