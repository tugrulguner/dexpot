"""Nested checked responses, public-field projection, and failure recovery."""

from __future__ import annotations

import os
from typing import Any, cast

import msgspec

from dexpot import Dex


class PublicItem(msgspec.Struct):
    name: str
    quantity: int = 1
    price: float = 2.5


class PrivateItem(msgspec.Struct):
    name: str
    quantity: int = 1
    price: float = 2.5
    supplier_secret: str = "vendor-only"


class PublicCatalog(msgspec.Struct):
    items: list[PublicItem]
    note: str = "ready"


class PrivateCatalog(msgspec.Struct):
    items: list[PrivateItem]
    note: str = "ready"
    internal_token: str = "hidden"


app = Dex()


@app.get("/catalog", response=PublicCatalog)
def catalog() -> PrivateCatalog:
    return PrivateCatalog([PrivateItem("tea", supplier_secret="vendor-only")])


@app.get("/invalid", response=PublicCatalog)
def invalid() -> PrivateCatalog:
    # Deliberately malformed nested value; the client sees only a sanitized error.
    return PrivateCatalog([PrivateItem(cast(Any, 7), supplier_secret="vendor-only")])


@app.get("/nonfinite", response=PublicCatalog)
def nonfinite() -> dict[str, object]:
    # Deliberately non-finite nested content, rejected by the checked response schema.
    return {"items": [{"name": "tea", "price": float("nan")}], "note": "ready"}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
