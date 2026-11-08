"""Runnable process-owned SQLite transactions example.

Run ``uv run python examples/database.py``. Set DEXPOT_EXAMPLE_DB to choose
the SQLite file and DEXPOT_EXAMPLE_POOL_SIZE for the fixed connection budget
(default 4). The demo serves one worker. Pool exhaustion returns HTTP 503
immediately. DEXPOT_EXAMPLE_EVENTS optionally records JSONL resource events.
The encoding-failure route intentionally commits before checked response
validation, demonstrating that an HTTP 500 cannot undo an already committed
transaction.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Iterator

import msgspec

from dexpot import Dex
from dexpot.app import HTTPError

app = Dex()
_state: dict[str, SQLitePool] = {}
_state_lock = threading.Lock()


def _event(name: str) -> None:
    path = os.environ.get("DEXPOT_EXAMPLE_EVENTS")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": name, "pid": os.getpid()}) + "\n")
        except OSError as error:
            logging.getLogger(__name__).warning("Could not write example event: %s", error)


class SQLitePool:
    """Fixed-size pool; a connection is exclusively leased to one handler."""

    def __init__(self, path: str, size: int):
        if path in ("", ":memory:"):
            raise ValueError("DEXPOT_EXAMPLE_DB must name a non-empty on-disk SQLite file")
        if size < 1:
            raise ValueError("DEXPOT_EXAMPLE_POOL_SIZE must be at least 1")
        self._available: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=size)
        self._all: list[sqlite3.Connection] = []
        try:
            for _ in range(size):
                connection = sqlite3.connect(path, timeout=0.25, check_same_thread=False)
                self._all.append(connection)
                connection.execute("PRAGMA busy_timeout = 250")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS items ("
                    "id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL NOT NULL)"
                )
                self._available.put_nowait(connection)
        except BaseException:
            for connection in self._all:
                connection.close()
            raise

    @contextlib.contextmanager
    def lease(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = self._available.get_nowait()
        except queue.Empty:
            raise HTTPError(503, "database connection pool exhausted") from None
        _event("acquire")
        try:
            yield connection
        finally:
            _event("release")
            self._available.put_nowait(connection)

    def close(self) -> None:
        for connection in self._all:
            connection.close()
        _event("close")


@contextlib.contextmanager
def database_resource() -> Iterator[None]:
    raw_size = os.environ.get("DEXPOT_EXAMPLE_POOL_SIZE", "4")
    try:
        size = int(raw_size)
    except ValueError as error:
        raise ValueError("DEXPOT_EXAMPLE_POOL_SIZE must be an integer") from error
    if size < 1:
        raise ValueError("DEXPOT_EXAMPLE_POOL_SIZE must be at least 1")
    pool = SQLitePool(os.environ.get("DEXPOT_EXAMPLE_DB", "items.sqlite3"), size)
    with _state_lock:
        _state["pool"] = pool
    _event("open")
    try:
        yield
    finally:
        with _state_lock:
            _state.pop("pool", None)
        pool.close()


app.lifespan(database_resource)


def _pool() -> SQLitePool:
    with _state_lock:
        return _state["pool"]


class ItemIn(msgspec.Struct):
    name: str
    price: float


class ExpectedItem(msgspec.Struct):
    id: int


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


def _insert(item: ItemIn) -> int:
    with _pool().lease() as connection:
        try:
            connection.execute("BEGIN")
            cursor = connection.execute(
                "INSERT INTO items(name, price) VALUES (?, ?)", (item.name, item.price)
            )
            item_id = cursor.lastrowid
            connection.commit()
            _event("commit")
            if item_id is None:
                raise RuntimeError("SQLite did not return an inserted row id")
            return item_id
        except BaseException:
            connection.rollback()
            _event("rollback")
            raise


@app.post("/items", body=ItemIn, response=None)
def create_item(item: ItemIn) -> tuple[int, dict[str, object]]:
    item_id = _insert(item)
    return 201, {"id": item_id, "name": item.name, "price": item.price}


@app.get("/items/{item_id}", response=None)
def get_item(item_id: int) -> dict[str, object] | tuple[int, dict[str, str]]:
    if not -9223372036854775808 <= item_id <= 9223372036854775807:
        return 404, {"detail": "item not found"}
    with _pool().lease() as connection:
        row = connection.execute(
            "SELECT id, name, price FROM items WHERE id = ?", (item_id,)
        ).fetchone()
    if row is None:
        return 404, {"detail": "item not found"}
    return {"id": row[0], "name": row[1], "price": row[2]}


@app.post("/rollback", body=ItemIn)
def rollback_demo(item: ItemIn) -> dict[str, bool]:
    with _pool().lease() as connection:
        try:
            connection.execute("BEGIN")
            connection.execute(
                "INSERT INTO items(name, price) VALUES (?, ?)", (item.name, item.price)
            )
            raise HTTPError(409, "write rolled back by demonstration")
        except BaseException:
            connection.rollback()
            _event("rollback")
            raise


@app.post("/encoding-failure", body=ItemIn, response=ExpectedItem)
def encoding_failure(item: ItemIn) -> dict[str, object]:
    _insert(item)
    return {"id": "wrong type"}


@app.post("/hold", body=ItemIn, response=None)
def hold_lease(item: ItemIn) -> tuple[int, dict[str, object]]:
    with _pool().lease():
        time.sleep(0.8)
    item_id = _insert(item)
    return 201, {"id": item_id, "name": item.name, "price": item.price}


if __name__ == "__main__":
    os.environ["DEXPOT_WORKERS"] = "1"
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
