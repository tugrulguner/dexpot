from __future__ import annotations

import sys
from types import ModuleType
from typing import ForwardRef

import msgspec
import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from dexpot import Dex
from dexpot._openapi import _declarative
from test_openapi_attrs_http import exchange


def raw_namespace(module):
    return vars(ModuleType)["__dict__"].__get__(module)


def view(module):
    raw = raw_namespace(module)
    raw["reads"] += 1
    namespace = raw.copy()
    namespace["Alias"] = raw["Text"] if raw["reads"] == 1 else raw["Integer"]
    return namespace


class GetterModule(ModuleType):
    def __getattribute__(self, name):
        if name == "__dict__":
            return view(self)
        return ModuleType.__getattribute__(self, name)


class DescriptorModule(ModuleType):
    @property
    def __dict__(self):
        return view(self)


class PlainModule(ModuleType):
    pass


def model(monkeypatch, module_type, suffix):
    module = module_type(f"_openapi_module_{module_type.__name__}_{suffix}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    raw = raw_namespace(module)
    exec(
        compile(
            "from __future__ import annotations\nimport msgspec\n"
            "class Text(msgspec.Struct):\n value:str\n"
            "class Integer(msgspec.Struct):\n value:int\nAlias=Text\n"
            "class Body(msgspec.Struct):\n value:Alias\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        raw,
    )
    raw["reads"] = 0
    return raw


@pytest.mark.parametrize("module_type", [GetterModule, DescriptorModule])
def test_opaque_module_namespace_rejects_before_exporter_reads(monkeypatch, module_type):
    control = model(monkeypatch, module_type, "native")
    ordinary = Dex()
    ordinary.post("/value", body=control["Body"])(lambda body: msgspec.to_builtins(body))
    native_reads = control["reads"]
    assert exchange(ordinary, {"value": {"value": "ok"}}) == (200, {"value": {"value": "ok"}})

    raw = model(monkeypatch, module_type, "export")
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="opaque"):
        app.post("/value", body=raw["Body"])(lambda body: None)
    assert raw["reads"] == native_reads
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


@pytest.mark.parametrize("module_type", [ModuleType, PlainModule])
def test_ordinary_module_namespace_keeps_schema_and_http_aligned(monkeypatch, module_type):
    raw = model(monkeypatch, module_type, "static")
    app = Dex(openapi=True)
    called = []

    @app.post("/value", body=raw["Body"])
    def handler(body):
        payload = msgspec.to_builtins(body)
        called.append(payload)
        return payload

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
    assert raw["reads"] == 0


@pytest.mark.parametrize("module_type", [GetterModule, DescriptorModule])
@pytest.mark.parametrize("wrapper", ["forwardref", "alias"])
def test_wrapped_module_namespace_rejects_without_reading_dictionary(
    monkeypatch, module_type, wrapper
):
    raw = model(monkeypatch, module_type, wrapper)
    if wrapper == "forwardref":
        annotation = ForwardRef("Alias", module=raw["__name__"])
    else:
        exec("type Wire = int", raw)
        annotation = raw["Wire"]
    with pytest.raises(TypeError, match="opaque"):
        _declarative(annotation, {})
    assert raw["reads"] == 0
