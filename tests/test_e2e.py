"""End-to-end tests: real HTTP against the real server on a random port."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import msgspec
import pytest

from dexpot import Dex


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def server():
    app = Dex()

    class Item(msgspec.Struct):
        name: str
        price: float

    class ItemOut(msgspec.Struct):
        name: str
        price: float
        id: int

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/items/{item_id}", response=ItemOut)
    def get_item(item_id: int) -> ItemOut:
        return ItemOut(name=f"item{item_id}", price=float(item_id), id=item_id)

    @app.post("/items", body=Item, response=ItemOut)
    def create_item(item: Item) -> ItemOut:
        return ItemOut(name=item.name, price=item.price, id=42)

    @app.get("/boom")
    def boom() -> dict:
        raise ValueError("kaboom")

    port = _free_port()
    t = threading.Thread(target=app.serve, kwargs={"host": "127.0.0.1", "port": port}, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{base}/health", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield base
    # daemon thread dies with the test process


def test_health(server):
    r = httpx.get(f"{server}/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_path_param_typed_response(server):
    r = httpx.get(f"{server}/items/7")
    assert r.status_code == 200
    assert r.json() == {"name": "item7", "price": 7.0, "id": 7}


def test_post_validated_body(server):
    r = httpx.post(f"{server}/items", json={"name": "x", "price": 3.5})
    assert r.status_code == 200
    assert r.json() == {"name": "x", "price": 3.5, "id": 42}


def test_invalid_body_422(server):
    r = httpx.post(f"{server}/items", json={"bad": True})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_handler_exception_500(server):
    r = httpx.get(f"{server}/boom")
    assert r.status_code == 500
    assert "ValueError" in r.json()["detail"]


def test_404(server):
    r = httpx.get(f"{server}/nope")
    assert r.status_code == 404


def test_keep_alive_many_requests(server):
    with httpx.Client(base_url=server) as c:
        for _i in range(50):
            r = c.get("/items/3")
            assert r.status_code == 200
