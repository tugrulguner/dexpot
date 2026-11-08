"""Opt-in OpenAPI 3.1 snapshots (dexpot 0.9.0 or newer).

Run: uv run python examples/openapi.py
Export without listening: uv run python examples/openapi.py --export openapi.json
The document route is application code, not an automatically enabled framework endpoint.
"""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path
from typing import Annotated

import msgspec

from dexpot import Cookie, Dex, Header, Query, RawResponse

NonemptyName = Annotated[str, msgspec.Meta(min_length=1)]
NonnegativePrice = Annotated[float, msgspec.Meta(ge=0)]


class ItemIn(msgspec.Struct):
    name: NonemptyName
    price: NonnegativePrice


class ItemOut(msgspec.Struct):
    id: int
    name: str
    price: float
    limit: int
    request_id: str
    theme: str


class _PrivateItemOut(ItemOut):
    internal_note: str


app = Dex(openapi=True)
_lock = threading.Lock()
_created = 0
_document = b""


@app.post("/items/{item_id}", body=ItemIn, response=ItemOut)
def create_item(
    item_id: int,
    payload: ItemIn,
    *,
    limit: Annotated[int, Query("limit")] = 20,
    request_id: Annotated[str, Header("x-request-id")],
    theme: Annotated[str, Cookie("theme")] = "light",
):
    """Create a fixture item with explicitly bound request metadata."""
    global _created
    with _lock:
        _created += 1
    return 201, _PrivateItemOut(
        item_id, payload.name, payload.price, limit, request_id, theme, "server-only"
    )


@app.get("/stats", response=int)
def stats():
    """Count successful creation handlers in this serving process."""
    with _lock:
        return _created


@app.get("/openapi.json")
def specification():
    """Serve the precomputed document without regenerating schemas."""
    return RawResponse(_document, content_type="application/json")


_document = msgspec.json.encode(app.openapi(title="Fixture items", version="development"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, metavar="PATH")
    args = parser.parse_args()
    if args.export is not None:
        try:
            with args.export.open("xb") as target:
                target.write(_document)
                target.write(b"\n")
        except FileExistsError:
            parser.error(f"refusing to overwrite {args.export}")
    else:
        app.serve(host="127.0.0.1", port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")))
