"""Show paired process-scoped setup and cleanup (requires dexpot >= 0.8.0)."""

from __future__ import annotations

import contextlib
import os

from dexpot import Dex

app = Dex()


@contextlib.contextmanager
def cache_resource():
    cache: dict[str, str] = {}
    try:
        yield cache
    finally:
        cache.clear()


app.lifespan(cache_resource)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
