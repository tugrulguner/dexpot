import sys
from typing import Any, cast

import msgspec
import pytest

from dexpot._plans import _checked_fallback
from dexpot._response import compile_preparer


@pytest.mark.skipif(
    sys.platform != "darwin" or getattr(sys, "_is_gil_enabled", lambda: True)(),
    reason="Darwin FT native flat-contract preparation",
)
def test_flat_struct_uses_native_checked_preparation():
    class Small(msgspec.Struct):
        name: str

    registrations = []

    def fallback(schema):
        registrations.append(schema)
        return _checked_fallback(schema)

    prepare = compile_preparer(Small, fallback)
    assert registrations == [Small]
    assert prepare(Small("alice")) == {"name": "alice"}
    with pytest.raises(ValueError):
        prepare(Small(cast(Any, 123)))


def test_flat_native_path_projects_private_subtype_and_rejects_context():
    from dexpot import Request

    class Public(msgspec.Struct):
        name: str

    class Private(Public):
        secret: Any

    prepare = compile_preparer(Public, _checked_fallback)
    assert prepare(Private("alice", "private")) == {"name": "alice"}
    with pytest.raises(TypeError):
        prepare(Private("alice", Request(method="GET", path="/", params={}, query="", headers={})))


def test_flat_factory_and_post_init_keep_compiled_path():
    factories = []

    def default_name():
        factories.append("factory")
        return "alice"

    class FactoryDefault(msgspec.Struct):
        name: str = msgspec.field(default_factory=default_name)

    class PostInit(msgspec.Struct):
        name: str

        def __post_init__(self):
            self.name = self.name.upper()

    for schema in (FactoryDefault, PostInit):
        registrations = []

        def fallback(annotation, registrations=registrations):
            registrations.append(annotation)
            return _checked_fallback(annotation)

        prepare = compile_preparer(schema, fallback)
        assert not registrations
        assert not factories
        if schema is FactoryDefault:
            assert prepare({}) == {"name": "alice"}
            assert factories == ["factory"]
            factories.clear()
        else:
            assert prepare(PostInit("alice")) == {"name": "ALICE"}


@pytest.mark.skipif(
    sys.platform != "darwin" or getattr(sys, "_is_gil_enabled", lambda: True)(),
    reason="Darwin FT native flat-contract preparation",
)
def test_flat_endpoint_reuses_typed_validated_bytes(monkeypatch):
    from dexpot._plans import EndpointPlan

    class Public(msgspec.Struct):
        name: str

    plan = EndpointPlan("GET", "/", lambda: None, None, Public, "", [])

    def forbidden_untyped_decode(*args, **kwargs):
        raise AssertionError("validated native bytes must not be decoded and re-encoded")

    monkeypatch.setattr(msgspec.json, "decode", forbidden_untyped_decode)
    assert plan.encode(Public("alice")) == b'{"name":"alice"}'
    with pytest.raises(ValueError):
        plan.encode(Public(cast(Any, 123)))


def test_flat_native_path_keeps_registration_field_metadata():
    class Public(msgspec.Struct):
        name: str

    prepare = compile_preparer(Public, _checked_fallback)
    Public.__annotations__["name"] = int
    assert prepare(Public("alice")) == {"name": "alice"}
