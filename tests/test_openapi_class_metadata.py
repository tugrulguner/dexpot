from __future__ import annotations

import sys
from types import ModuleType

import msgspec
import pytest
from openapi_spec_validator import validate

from dexpot import Dex
from dexpot._openapi import _ordinary_attribute_access
from test_openapi_attrs_http import exchange


def fixture(monkeypatch, kind, suffix):
    module = ModuleType(f"_openapi_class_metadata_{kind}_{suffix}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    metadata = {
        "dict": " @property\n def __dict__(cls):\n  reads.append(1)\n  result=dict(vars(type)['__dict__'].__get__(cls))\n  result['Alias']=Text if len(reads)==1 else Integer\n  return result\n",
        "annotations": " @property\n def __annotations__(cls):\n  reads.append(1)\n  return {'value':str}\n",
        "plain": " pass\n",
    }[kind]
    field = "'choose()'" if kind == "annotations" else "str"
    source = (
        "import msgspec\nfrom dataclasses import dataclass\nreads=[]\ncalls=[]\n"
        "def choose():\n calls.append(1)\n return str if len(calls)==1 else int\n"
        f"class Text(msgspec.Struct):\n value:{field}\n"
        "class Integer(msgspec.Struct):\n value:int\nclass Meta(type):\n"
        + metadata
        + "@dataclass\nclass Body(metaclass=Meta):\n Alias=Text\n value:'Alias'\nreads.clear()\n"
    )
    exec(compile(source, module.__name__, "exec", dont_inherit=True), vars(module))
    return module


@pytest.mark.parametrize("kind", ["dict", "annotations"])
def test_opaque_class_metadata_rejects_atomically_without_exporter_reads(monkeypatch, kind):
    control = fixture(monkeypatch, kind, "native")
    ordinary = Dex()
    ordinary.post("/value", body=control.Body)(lambda body: msgspec.to_builtins(body))
    native_reads = len(control.reads)
    assert exchange(ordinary, {"value": {"value": "ok"}}) == (200, {"value": {"value": "ok"}})
    module = fixture(monkeypatch, kind, "export")
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="opaque"):
        app.post("/value", body=module.Body)(lambda body: None)
    assert len(module.reads) == native_reads
    assert len(module.calls) <= 1
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


def test_transparent_metaclass_keeps_native_http_and_schema(monkeypatch):
    module = fixture(monkeypatch, "plain", "control")
    app = Dex(openapi=True)
    app.post("/value", body=module.Body)(lambda body: msgspec.to_builtins(body))
    doc = app.openapi()
    validate(doc)
    assert any(
        s.get("properties", {}).get("value", {}).get("type") == "string"
        for s in doc["components"]["schemas"].values()
    )
    assert exchange(app, {"value": {"value": "ok"}}) == (200, {"value": {"value": "ok"}})
    assert exchange(app, {"value": {"value": 1}})[0] == 422


@pytest.mark.parametrize(
    "name", ["__type_params__", "__mro__", "__bases__", "__module__", "__name__"]
)
def test_other_opaque_metadata_descriptors_reject_without_getter_execution(name):
    reads = []

    def getter(owner):
        reads.append(1)
        raise AssertionError("opaque getter was executed")

    meta = type("Meta", (type,), {name: property(getter)})
    owner = meta("Owner", (), {})
    with pytest.raises(TypeError, match="opaque"):
        _ordinary_attribute_access(owner)
    assert reads == []


def test_dataclass_field_descriptor_cannot_change_requiredness(monkeypatch):
    module = ModuleType("_openapi_dataclass_fields")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(
        compile(
            "import copy\nfrom dataclasses import dataclass,fields,MISSING\n"
            "@dataclass\nclass Base:\n value:int=7\n"
            "optional={'value':fields(Base)[0]}\nfield=copy.copy(optional['value'])\n"
            "field.default=MISSING\nrequired={'value':field}\nreads=[]\n"
            "class Meta(type):\n @property\n def __dataclass_fields__(cls):\n"
            "  reads.append(1)\n  return optional if len(reads)==1 else required\n"
            "class Body(Base,metaclass=Meta):\n pass\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        vars(module),
    )
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="opaque"):
        app.post("/value", body=module.Body)(lambda body: None)
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


@pytest.mark.parametrize(
    "name",
    [
        "__dataclass_fields__",
        "__attrs_attrs__",
        "__struct_fields__",
        "__struct_defaults__",
        "__required_keys__",
        "__optional_keys__",
        "__total__",
        "_fields",
        "_field_defaults",
    ],
)
def test_opaque_native_family_metadata_rejects_without_executing_descriptor(name):
    reads = []

    def getter(owner):
        reads.append(1)
        raise AssertionError("opaque native metadata getter executed")

    meta = type("Meta", (type,), {name: property(getter)})
    owner = meta("Owner", (), {})
    with pytest.raises(TypeError, match="opaque"):
        _ordinary_attribute_access(owner)
    assert reads == []


def test_normal_dataclass_defaults_remain_optional_on_wire_and_in_schema():
    from dataclasses import dataclass

    class Meta(type):
        pass

    @dataclass
    class Body(metaclass=Meta):
        value: int = 7

    app = Dex(openapi=True)
    app.post("/value", body=Body)(lambda body: {"value": body.value})
    doc = app.openapi()
    validate(doc)
    component = next(s for s in doc["components"]["schemas"].values() if s.get("title") == "Body")
    assert "value" not in component.get("required", [])
    assert component["properties"]["value"]["default"] == 7
    assert exchange(app, {}) == (200, {"value": 7})
    assert exchange(app, {"value": "bad"})[0] == 422


def test_fallback_attribute_getter_cannot_fabricate_native_field_metadata(monkeypatch):
    module = ModuleType("_openapi_fallback_fields")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(
        compile(
            "import copy\nfrom dataclasses import dataclass,fields,MISSING\n"
            "@dataclass\nclass Base:\n value:int=7\n"
            "optional={'value':fields(Base)[0]}\nfield=copy.copy(optional['value'])\n"
            "field.default=MISSING\nrequired={'value':field}\nreads=[]\n"
            "class Meta(type):\n def __getattr__(cls,name):\n"
            "  if name!='__dataclass_fields__':raise AttributeError(name)\n"
            "  reads.append(1)\n  return optional if len(reads)==1 else required\n"
            "class Body(metaclass=Meta):\n value:int=7\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        vars(module),
    )
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="opaque"):
        app.post("/value", body=module.Body)(lambda body: {"value": body.value})
    assert app._endpoints == []
    assert app._openapi_registry.operations == []
    app.post("/value")(lambda: None)


def test_native_enum_attribute_access_remains_supported():
    from enum import IntEnum

    class Value(IntEnum):
        ONE = 1

    app = Dex(openapi=True)
    app.post("/value", body=Value)(lambda body: {"value": body.value})
    validate(app.openapi())
    assert exchange(app, 1) == (200, {"value": 1})
    assert exchange(app, 2)[0] == 422
