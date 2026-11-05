from __future__ import annotations

import pytest

from dexpot import Dex


def test_openapi_requires_explicit_opt_in() -> None:
    app = Dex()
    with pytest.raises(RuntimeError, match="openapi=True"):
        app.openapi()


def test_openapi_exports_detached_document_and_freezes_only_after_success() -> None:
    app = Dex(openapi=True)

    @app.get("/items/{item_id}", response=int)
    def item(item_id: int) -> int:
        return item_id

    with pytest.raises(TypeError):
        app.openapi(title="")
    document = app.openapi()
    assert document["openapi"] == "3.1.0"
    assert document["paths"]["/items/{item_id}"]["get"]["parameters"] == [
        {"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}}
    ]
    document["paths"].clear()
    assert "/items/{item_id}" in app.openapi()["paths"]
    with pytest.raises(RuntimeError, match="compiled"):
        app.get("/later")(lambda: None)


def test_openapi_disabled_does_not_import_capture_module() -> None:
    app = Dex()
    assert not hasattr(app, "_openapi_registry")
    with pytest.raises(RuntimeError):
        app.openapi()
