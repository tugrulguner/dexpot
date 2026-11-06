from __future__ import annotations

import sys
from types import ModuleType

import msgspec
import pytest
from openapi_spec_validator import validate

from dexpot import Dex


def aliases(monkeypatch, expression, dynamic):
    name = f"_openapi_alias_{dynamic}"
    module = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    field = "choose()" if dynamic else "str"
    source = f"""
from __future__ import annotations
from typing import Annotated, Literal
import msgspec
calls = []
alias_calls = []
def choose():
    calls.append(1)
    return str if len(calls) == 1 else int
class Child(msgspec.Struct):
    value: {field}
class Base:
    Alias = Child
    Choices = Literal
class Namespace(Base):
    pass
Types = {{"entry !": Child, "literal !": Literal}}
class Accessor:
    def __class_getitem__(cls, key):
        alias_calls.append(1)
        return Child
class Meta(type):
    @property
    def Constraint(cls):
        alias_calls.append(1)
        return msgspec.Meta(min_length=len(alias_calls))
    @property
    def Alias(cls):
        alias_calls.append(1)
        return Child
class Opaque(metaclass=Meta):
    pass
class Descriptor:
    def __get__(self, instance, owner):
        alias_calls.append(1)
        return Child
class Custom:
    Alias = Descriptor()
class UnionMeta(type):
    def __or__(cls, other):
        alias_calls.append(1)
        return Child
class UnionAlias(metaclass=UnionMeta):
    pass
class Body(msgspec.Struct):
    value: {expression}
"""
    exec(compile(source, name, "exec", dont_inherit=True), module.__dict__)
    return module


@pytest.mark.parametrize(
    "expression",
    [
        "Namespace.Alias",
        'Types["entry !"]',
        "Accessor[str]",
        "Opaque.Alias",
        "Custom.Alias",
        "UnionAlias | int",
        "Child if True else str",
    ],
)
def test_aliases_cannot_hide_dynamic_schema_annotations(monkeypatch, expression):
    module = aliases(monkeypatch, expression, True)
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=module.Body)(lambda body: None)
    assert module.calls == [1]
    assert len(module.alias_calls) <= 1
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


@pytest.mark.parametrize("expression", ["Namespace.Alias", 'Types["entry !"]'])
def test_static_dto_aliases_remain_supported(monkeypatch, expression):
    module = aliases(monkeypatch, expression, False)
    app = Dex(openapi=True)
    app.post("/value", body=module.Body)(lambda body: None)
    document = app.openapi()
    validate(document)
    assert app._endpoints[0].body_decoder.decode(b'{"value":{"value":"ok"}}').value.value == "ok"


def test_opaque_metadata_alias_is_not_reevaluated(monkeypatch):
    module = aliases(monkeypatch, "Annotated[str, Opaque.Constraint]", False)
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=module.Body)(lambda body: None)
    assert module.alias_calls == [1]
    assert app._endpoints == []


def test_literal_metadata_containers_are_values(monkeypatch):
    module = aliases(monkeypatch, "Annotated[str, ('choose()',)]", False)
    assert msgspec.json.Decoder(module.Body).decode(b'{"value":"ok"}').value == "ok"
    app = Dex(openapi=True)
    app.post("/value", body=module.Body)(lambda body: None)
    validate(app.openapi())


@pytest.mark.parametrize(
    "expression", ["Namespace.Choices['choose()']", "Types['literal !']['choose()']"]
)
def test_aliased_literal_strings_are_not_type_expressions(monkeypatch, expression):
    module = aliases(monkeypatch, expression, False)
    app = Dex(openapi=True)
    app.post("/value", body=module.Body)(lambda body: None)
    document = app.openapi()
    validate(document)
    assert app._endpoints[0].body_decoder.decode(b'{"value":"choose()"}').value == "choose()"
    owner = next(x for x in document["components"]["schemas"].values() if x.get("title") == "Body")
    assert owner["properties"]["value"]["enum"] == ["choose()"]
