from __future__ import annotations

import sys
from types import ModuleType

import msgspec
import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from dexpot import Dex
from test_openapi_attrs_http import exchange


def collision(monkeypatch, family, dynamic):
    module = ModuleType(f"_openapi_scope_{family}_{dynamic}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    declaration = {
        "struct": "class Body(msgspec.Struct):",
        "dataclass": "@dataclass\nclass Body:",
        "attrs": "@attrs.define\nclass Body:",
    }[family]
    field = "choose()" if dynamic else "str"
    source = (
        "from __future__ import annotations\nimport msgspec, attrs\n"
        "from dataclasses import dataclass\ncalls=[]\n"
        "def choose():\n calls.append(1)\n return str if len(calls)==1 else int\n"
        f"class Alias(msgspec.Struct):\n value:{field}\n"
        + declaration
        + "\n Alias=str\n value:Alias\n"
    )
    exec(compile(source, module.__name__, "exec", dont_inherit=True), vars(module))
    return module


@pytest.mark.parametrize("family", ["struct", "dataclass", "attrs"])
def test_class_alias_cannot_hide_native_module_owned_dynamic_model(monkeypatch, family):
    module = collision(monkeypatch, family, True)
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=module.Body)(lambda body: None)
    assert module.calls == [1]
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


@pytest.mark.parametrize("family", ["struct", "dataclass", "attrs"])
def test_static_module_alias_wins_class_shadow_in_schema_and_http(monkeypatch, family):
    module = collision(monkeypatch, family, False)
    app = Dex(openapi=True)
    called = []

    @app.post("/value", body=module.Body)
    def handler(body):
        value = msgspec.to_builtins(body)
        called.append(value)
        return value

    document = app.openapi()
    validate(document)
    schema = document["paths"]["/value"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    validator = Draft202012Validator({"allOf": [schema], "components": document["components"]})
    good = {"value": {"value": "ok"}}
    bad = {"value": {"value": 1}}
    assert validator.is_valid(good)
    assert not validator.is_valid(bad)
    assert exchange(app, good) == (200, good)
    assert exchange(app, bad)[0] == 422
    assert called == [good]
    assert module.calls == []


@pytest.mark.parametrize("inherited", [False, True])
def test_class_only_alias_fallback_remains_supported(monkeypatch, inherited):
    module = ModuleType(f"_openapi_scope_fallback_{inherited}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    source = (
        "from __future__ import annotations\nimport msgspec\n"
        "class Child(msgspec.Struct):\n value:str\n"
        "class Base(msgspec.Struct):\n Alias=Child\n value:Alias\n"
        + ("class Body(Base):\n pass\n" if inherited else "Body=Base\n")
    )
    exec(compile(source, module.__name__, "exec", dont_inherit=True), vars(module))
    app = Dex(openapi=True)
    app.post("/value", body=module.Body)(lambda body: msgspec.to_builtins(body))
    validate(app.openapi())
    assert exchange(app, {"value": {"value": "ok"}}) == (200, {"value": {"value": "ok"}})
    assert exchange(app, {"value": {"value": 1}})[0] == 422


def test_model_name_does_not_override_explicit_native_module_binding(monkeypatch):
    module = ModuleType("_openapi_scope_model_name")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(
        compile(
            "from __future__ import annotations\nimport msgspec\ncalls=[]\n"
            "def choose():\n calls.append(1)\n return str if len(calls)==1 else int\n"
            "class Alias(msgspec.Struct):\n value:choose()\n"
            "class Body(msgspec.Struct):\n value:Body\nRoot=Body\nBody=Alias\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        vars(module),
    )
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/value", body=module.Root)(lambda body: None)
    assert module.calls == [1]
    assert app._endpoints == []
