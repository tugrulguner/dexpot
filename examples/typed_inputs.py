"""Explicit scalar Query/Header/Cookie sources (dexpot 0.9.0 or newer).

Run: uv run python examples/typed_inputs.py.
The request-id header is tracing metadata, not authentication. GET /raw keeps
Request.query raw; no typed source binding is requested on that route.
"""

from __future__ import annotations

import os
from typing import Annotated

import msgspec

from dexpot import Cookie, Dex, Header, Query, Request


class Item(msgspec.Struct, frozen=True):
    id: int
    name: str
    category: str
    price: float
    archived: bool = False


ITEMS = (
    Item(1, "tea", "drinks", 2.5),
    Item(2, "coffee", "drinks", 4.0),
    Item(3, "aged tea", "drinks", 8.0, True),
    Item(4, "bread", "food", 3.0),
)
app = Dex()


@app.get("/items/{category}")
def list_items(
    category: str,
    *,
    limit: Annotated[int, Query("limit")] = 20,
    offset: Annotated[int, Query("offset")] = 0,
    min_price: Annotated[float, Query("min_price")] = 0.0,
    include_archived: Annotated[bool, Query("include_archived")] = False,
    request_id: Annotated[str, Header("x-request-id")],
    theme: Annotated[str, Cookie("theme")] = "light",
) -> dict[str, object] | tuple[int, dict[str, str]]:
    # Business ranges are application validation, separate from scalar parsing.
    if not 1 <= limit <= 100 or offset < 0:
        return 422, {"detail": "pagination out of range"}
    matching = [
        item
        for item in ITEMS
        if item.category == category
        and item.price >= min_price
        and (include_archived or not item.archived)
    ]
    return {
        "items": matching[offset : offset + limit],
        "limit": limit,
        "offset": offset,
        "min_price": min_price,
        "include_archived": include_archived,
        "request_id": request_id,
        "theme": theme,
    }


@app.get("/raw")
def raw_query(request: Request) -> dict[str, str]:
    return {"query": request.query}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
