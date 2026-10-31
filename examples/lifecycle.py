"""Process-local lifecycle resources (requires dexpot >= 0.8.0).

Run with ``uv run python examples/lifecycle.py``. ``GET /health`` preserves
its ``{"ok": true}`` response. ``PUT /cache/{key}`` stores a JSON
``{"value": "..."}``; ``GET /cache/{key}`` reads it (404 if absent).

Set ``DEXPOT_EXAMPLE_FAIL_STARTUP=check`` to demonstrate acquisition rollback
before the server opens its listener. Set ``DEXPOT_EXAMPLE_EVENTS`` to a path
to append JSONL acquisition/release events for lifecycle observation.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Iterator

import msgspec

from dexpot import Dex

app = Dex()


def _event(name: str) -> None:
    path = os.environ.get("DEXPOT_EXAMPLE_EVENTS")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": name}) + "\n")


class Cache:
    """Thread-safe process-local cache; safe for GIL and FT request threads."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


_state: dict[str, Cache] = {}
_state_lock = threading.Lock()


@contextlib.contextmanager
def cache_resource() -> Iterator[None]:
    cache = Cache()
    with _state_lock:
        _state["cache"] = cache
    _event("acquire:cache")
    try:
        yield
    finally:
        cache.clear()
        with _state_lock:
            _state.pop("cache", None)
        _event("release:cache")


@contextlib.contextmanager
def startup_check() -> Iterator[None]:
    """A later readiness check demonstrates rollback of the acquired cache."""
    _event("enter:check")
    try:
        if os.environ.get("DEXPOT_EXAMPLE_FAIL_STARTUP") == "check":
            raise RuntimeError("requested lifecycle startup failure at check")
        yield
    finally:
        _event("exit:check")


def _cache() -> Cache:
    with _state_lock:
        return _state["cache"]


app.lifespan(cache_resource)
app.lifespan(startup_check)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


class CacheValue(msgspec.Struct):
    value: str


@app.put("/cache/{key}", body=CacheValue)
def put_cache(key: str, item: CacheValue) -> dict[str, str]:
    _cache().put(key, item.value)
    return {"key": key, "value": item.value}


@app.get("/cache/{key}", response=None)
def get_cache(key: str) -> dict[str, str] | tuple[int, dict[str, str]]:
    value = _cache().get(key)
    if value is None:
        return 404, {"error": "not found"}
    return {"key": key, "value": value}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
