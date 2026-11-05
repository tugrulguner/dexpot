from __future__ import annotations

import msgspec
import pytest

from dexpot import Dex


class RefData(msgspec.Struct, frozen=True):
    value: str = msgspec.field(name="$ref", default="https://data.invalid/value")


class Envelope(msgspec.Struct):
    data: RefData = RefData()


def test_reference_named_properties_and_payload_defaults_are_data_not_schema_refs():
    app = Dex(openapi=True)
    app.post("/value", body=Envelope)(lambda body: None)
    document = app.openapi()
    components = document["components"]["schemas"]
    ref_data = next(value for value in components.values() if value.get("title") == "RefData")
    envelope = next(value for value in components.values() if value.get("title") == "Envelope")
    assert ref_data["properties"]["$ref"]["type"] == "string"
    assert envelope["properties"]["data"]["default"] == {"$ref": "https://data.invalid/value"}


_annotation_calls = []


def changing_type():
    _annotation_calls.append(1)
    return str if len(_annotation_calls) == 1 else int


class DynamicBody(msgspec.Struct):
    value: str


DynamicBody.__annotations__["value"] = "changing_type()"


def test_dynamic_postponed_annotation_is_rejected_without_schema_re_evaluation():
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="declarative"):
        app.post("/dynamic", body=DynamicBody)(lambda body: body)
    assert len(_annotation_calls) == 1  # The incumbent decoder, not schema generation.
    app.post("/dynamic")(lambda: None)
