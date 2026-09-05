"""Runnable typed CRUD API with thread-safe shared in-process state."""

from __future__ import annotations

import os
import threading

import msgspec

from dexpot import Dex, Request

app = Dex()


class ItemIn(msgspec.Struct):
    name: str
    price: float


class Item(msgspec.Struct):
    id: int
    name: str
    price: float


_items: dict[int, Item] = {1: Item(id=1, name="starter", price=9.99)}
_next_id = 2
_lock = threading.Lock()


@app.get("/items/{item_id}", response=Item)
def get_item(item_id: int) -> Item | tuple[int, dict[str, str]]:
    with _lock:
        item = _items.get(item_id)
    if item is None:
        return 404, {"detail": "item not found"}
    return item


@app.get("/context/{item_id}")
def request_context(item_id: int, request: Request) -> dict[str, object]:
    return {
        "method": request.method,
        "path": request.path,
        "params": request.params,
        "query": request.query,
    }


@app.post("/items", body=ItemIn, response=Item)
def create_item(item: ItemIn) -> tuple[int, Item]:
    global _next_id
    with _lock:
        created = Item(id=_next_id, name=item.name, price=item.price)
        _items[_next_id] = created
        _next_id += 1
    return 201, created


@app.put("/items/{item_id}", body=ItemIn, response=Item)
def replace_item(item_id: int, item: ItemIn) -> Item | tuple[int, dict[str, str]]:
    with _lock:
        if item_id not in _items:
            return 404, {"detail": "item not found"}
        replaced = Item(id=item_id, name=item.name, price=item.price)
        _items[item_id] = replaced
    return replaced


@app.delete("/items/{item_id}")
def delete_item(item_id: int) -> tuple[int, dict[str, object]]:
    with _lock:
        if _items.pop(item_id, None) is None:
            return 404, {"detail": "item not found"}
    return 200, {"deleted": item_id}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
