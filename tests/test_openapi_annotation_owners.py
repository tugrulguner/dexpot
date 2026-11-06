from __future__ import annotations

import sys
from types import ModuleType

import msgspec
import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from dexpot import Dex


def fixture_type(monkeypatch, family, wrapped, dynamic):
    name = f"_openapi_owner_{family}_{wrapped}_{dynamic}"
    module = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    declaration = {
        "struct": "class Owner(msgspec.Struct):",
        "dataclass": "@dataclass\nclass Owner:",
        "typeddict": "class Owner(TypedDict):",
        "extensions": "class Owner(ExtensionsTypedDict):",
        "namedtuple": "class Owner(NamedTuple):",
    }[family]
    annotation = "choose()" if dynamic else "Text"
    source = f"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Literal, NamedTuple, NewType, TypedDict
from typing_extensions import TypedDict as ExtensionsTypedDict
import msgspec
calls = []
def choose():
    calls.append(1)
    return str if len(calls) == 1 else int
Text = Annotated[str, msgspec.Meta(min_length=2)]
{declaration}
    value: {annotation}
Alias = NewType("Alias", Owner)
class Wrapper(msgspec.Struct):
    value: Alias
"""
    exec(compile(source, name, "exec", dont_inherit=True), module.__dict__)
    return module, module.Wrapper if wrapped else module.Owner


@pytest.mark.parametrize("family", ["struct", "dataclass", "typeddict", "namedtuple", "extensions"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_dynamic_native_annotation_owners_reject_atomically(monkeypatch, family, wrapped):
    module, schema = fixture_type(monkeypatch, family, wrapped, True)
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=schema)(lambda body: None)
    # Only the incumbent decoder may evaluate the annotation, never schema generation.
    assert module.calls == [1]
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)
    validate(app.openapi())


@pytest.mark.parametrize("family", ["struct", "dataclass", "typeddict", "namedtuple", "extensions"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_static_native_annotation_owners_preserve_constraints(monkeypatch, family, wrapped):
    module, schema = fixture_type(monkeypatch, family, wrapped, False)
    app = Dex(openapi=True)
    app.post("/value", body=schema)(lambda body: None)
    document = app.openapi()
    validate(document)
    body_schema = document["paths"]["/value"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    validator = Draft202012Validator({"allOf": [body_schema], "components": document["components"]})
    for value, accepted in [("ok", True), ("x", False)]:
        payload = [value] if family == "namedtuple" else {"value": value}
        if wrapped:
            payload = {"value": payload}
        assert validator.is_valid(payload) is accepted
        if accepted:
            app._endpoints[0].body_decoder.decode(msgspec.json.encode(payload))
        else:
            with pytest.raises(msgspec.ValidationError):
                app._endpoints[0].body_decoder.decode(msgspec.json.encode(payload))
    assert module.calls == []
