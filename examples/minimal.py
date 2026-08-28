"""Smallest runnable dexpot application: typed path capture and response."""

from __future__ import annotations

import os

from msgspec import Struct

from dexpot import Dex

app = Dex()


class ItemOut(Struct):
    id: int
    name: str
    price: float


@app.get("/items/{item_id}", response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    """Return one typed item."""
    return ItemOut(id=item_id, name=f"item-{item_id}", price=float(item_id))


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
