from __future__ import annotations

import gc
import sys
import typing
import weakref
from types import ModuleType

import msgspec
import pytest

from dexpot import Dex, Response
from test_openapi_attrs_http import exchange


def model(monkeypatch, family="struct"):
    module = ModuleType(f"_openapi_reused_model_{family}")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    declaration = {
        "struct": "class Body(msgspec.Struct):",
        "dataclass": "@dataclass\nclass Body:",
        "attrs": "@attrs.define\nclass Body:",
        "typeddict": "class Body(TypedDict):",
        "extensions": "class Body(ExtensionsTypedDict):",
        "namedtuple": "class Body(NamedTuple):",
    }[family]
    exec(
        compile(
            "from __future__ import annotations\nimport msgspec,attrs\nfrom dataclasses import dataclass\n"
            "from typing import TypedDict,NamedTuple\nfrom typing_extensions import TypedDict as ExtensionsTypedDict\nAlias=str\n"
            + declaration
            + "\n value:Alias\n"
            "class Wrapper(msgspec.Struct):\n value:Body\n",
            module.__name__,
            "exec",
            dont_inherit=True,
        ),
        module.__dict__,
    )
    return module


@pytest.mark.parametrize("mutation", ["alias", "annotations"])
@pytest.mark.parametrize("other_app", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "family", ["struct", "dataclass", "attrs", "typeddict", "extensions", "namedtuple"]
)
def test_changed_captured_models_reject_atomically(
    monkeypatch, mutation, other_app, nested, family
):
    module = model(monkeypatch, family)
    original = Dex(openapi=True)
    original.post("/value", body=module.Body)(lambda body: Response(msgspec.to_builtins(body)))
    if mutation == "alias":
        vars(module)["Alias"] = int
    else:
        module.Body.__annotations__["value"] = int
    app = Dex(openapi=True) if other_app else original
    before = len(app._endpoints)
    with pytest.raises(TypeError, match=r"changed.*model|model.*changed"):
        app.post("/after", body=module.Wrapper if nested else module.Body)(lambda body: None)
    assert len(app._endpoints) == before
    assert len(app._openapi_registry.operations) == before
    app.post("/after")(lambda: None)
    document = original.openapi()
    body = next(s for s in document["components"]["schemas"].values() if s.get("title") == "Body")
    field_schema = body["prefixItems"][0] if family == "namedtuple" else body["properties"]["value"]
    assert field_schema["type"] == "string"
    original._endpoints[0].body_decoder.decode(
        b'["ok"]' if family == "namedtuple" else b'{"value":"ok"}'
    )
    payload = ["ok"] if family == "namedtuple" else {"value": "ok"}
    assert exchange(original, payload) == (200, payload)


def test_unchanged_model_can_be_reused_across_apps_and_roles(monkeypatch):
    module = model(monkeypatch)
    for _ in range(2):
        app = Dex(openapi=True)
        app.post("/first", body=module.Body, response=module.Body)(lambda body: body)
        app.post("/second", body=module.Wrapper)(lambda body: None)
        assert len(app.openapi()["paths"]) == 2


def test_fingerprints_do_not_retain_temporary_model_classes():
    from dexpot._openapi import _MODEL_SCHEMAS

    def capture():
        class Temporary(msgspec.Struct):
            value: str

        app = Dex(openapi=True)
        app.post("/value", body=Temporary)(lambda body: None)
        return weakref.ref(Temporary), id(Temporary)

    reference, key = capture()
    # Python 3.12's typing LRU retains Tuple[Temporary] made by native schema
    # inspection. Clear that independent cache before testing our weak ownership.
    for cleanup in getattr(typing, "_cleanups", ()):
        cleanup()
    gc.collect()
    assert reference() is None
    assert key not in _MODEL_SCHEMAS
