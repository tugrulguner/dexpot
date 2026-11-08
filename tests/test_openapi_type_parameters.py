from __future__ import annotations

import sys
from types import ModuleType

import msgspec
import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from dexpot import Dex, Response
from test_openapi_attrs_http import exchange


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize(
    "family", ["struct", "dataclass", "attrs", "typeddict", "extensions", "namedtuple"]
)
def test_pep695_generic_schema_matches_native_and_http(monkeypatch, family, future):
    module = ModuleType(f"_openapi_pep695_{family}_{future}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    declaration = {
        "struct": "class Box[T](msgspec.Struct):",
        "dataclass": "@dataclass\nclass Box[T]:",
        "attrs": "@attrs.define\nclass Box[T]:",
        "typeddict": "class Box[T](TypedDict):",
        "extensions": "class Box[T](ExtensionsTypedDict):",
        "namedtuple": "class Box[T](NamedTuple):",
    }[family]
    source = ("from __future__ import annotations\n" if future else "") + (
        "import msgspec,attrs\nfrom dataclasses import dataclass\n"
        "from typing import NamedTuple,TypedDict\nfrom typing_extensions import TypedDict as ExtensionsTypedDict\n"
        + declaration
        + "\n value:T\n"
    )
    exec(compile(source, module.__name__, "exec", dont_inherit=True), vars(module))
    schema_type = module.Box[int]
    # Old msgspec versions do not resolve postponed PEP695 parameters natively.
    # This feature must preserve native admission, not repair that dependency.
    try:
        decoder = msgspec.json.Decoder(schema_type)
    except NameError as error:
        if error.name != "T":
            raise
        pytest.skip(f"Native msgspec cannot resolve postponed type parameter: {error}")
    app = Dex(openapi=True)
    called = []

    @app.post("/value", body=schema_type)
    def handler(body):
        payload = msgspec.to_builtins(body)
        called.append(payload)
        return Response(payload)

    document = app.openapi()
    validate(document)
    schema = document["paths"]["/value"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    validator = Draft202012Validator({"allOf": [schema], "components": document["components"]})
    good = [1] if family == "namedtuple" else {"value": 1}
    bad = ["bad"] if family == "namedtuple" else {"value": "bad"}
    decoder.decode(msgspec.json.encode(good))
    assert validator.is_valid(good)
    assert not validator.is_valid(bad)
    assert exchange(app, good) == (200, good)
    assert exchange(app, bad)[0] == 422
    assert called == [tuple(good) if family == "namedtuple" else good]


def test_module_binding_shadowing_a_type_parameter_cannot_hide_dynamic_model(monkeypatch):
    module = ModuleType("_openapi_pep695_shadow")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(
        compile(
            "from __future__ import annotations\nimport msgspec\ncalls=[]\n"
            "def choose():\n calls.append(1)\n return str if len(calls)==1 else int\n"
            "class T(msgspec.Struct):\n value:choose()\n"
            "class Box[T](msgspec.Struct):\n value:T\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        vars(module),
    )
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=module.Box[int])(lambda body: None)
    assert module.calls == [1]
    assert app._endpoints == []


def test_static_module_shadow_keeps_native_scope_precedence(monkeypatch):
    module = ModuleType("_openapi_pep695_static_shadow")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(
        compile(
            "from __future__ import annotations\nimport msgspec\nT=str\n"
            "class Box[T](msgspec.Struct):\n value:T\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        vars(module),
    )
    app = Dex(openapi=True)
    app.post("/value", body=module.Box[int])(lambda body: msgspec.to_builtins(body))
    document = app.openapi()
    component = next(iter(document["components"]["schemas"].values()))
    assert component["properties"]["value"]["type"] == "string"
    assert exchange(app, {"value": "ok"}) == (200, {"value": "ok"})
    assert exchange(app, {"value": 1})[0] == 422
