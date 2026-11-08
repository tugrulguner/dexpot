from __future__ import annotations

from typing import Annotated

import msgspec
import pytest

from dexpot import Dex


def test_conflicting_template_names_reject_before_publication():
    app = Dex(openapi=True)
    app.get("/items/{item_id}")(lambda item_id: item_id)
    with pytest.raises(TypeError, match="templated"):
        app.post("/items/{name}")(lambda name: name)
    app.post("/items/{item_id}")(lambda item_id: item_id)
    assert set(app.openapi()["paths"]["/items/{item_id}"]) == {"get", "post"}


@pytest.mark.parametrize(
    "reference", ["https://schema.invalid/remote", "#/components/schemas/Missing"]
)
def test_unresolved_or_external_schema_refs_reject_atomically(reference):
    annotation = Annotated[str, msgspec.Meta(extra_json_schema={"$ref": reference})]
    schema = msgspec.defstruct("RefBody", [("value", annotation)])
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="reference"):
        app.post("/value", body=schema)(lambda body: None)
    app.post("/value")(lambda: None)


def test_nonfinite_schema_default_is_not_silently_changed_to_null():
    schema = msgspec.defstruct("Nonfinite", [("value", float, float("nan"))])
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="non-finite"):
        app.post("/value", body=schema)(lambda body: None)
    app.post("/value")(lambda: None)


@pytest.mark.parametrize(
    "kwargs", [{"title": ""}, {"title": 1}, {"version": ""}, {"version": None}]
)
def test_bad_document_metadata_does_not_freeze_registration(kwargs):
    app = Dex(openapi=True)
    with pytest.raises(TypeError):
        app.openapi(**kwargs)
    app.get("/later")(lambda: None)


@pytest.mark.parametrize("flag", [None, 1, "true"])
def test_opt_in_must_be_an_explicit_boolean(flag):
    with pytest.raises(TypeError, match="bool"):
        Dex(openapi=flag)
