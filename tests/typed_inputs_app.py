"""Real-server fixture for the explicit scalar-source contract."""

import os
import threading
from typing import Annotated

import msgspec

from dexpot import Cookie, Dex, Header, Query, Request

app = Dex()
_lock = threading.Lock()
_calls = 0


def scalar(path, annotation, default):
    def handler(value):
        global _calls
        with _lock:
            _calls += 1
        return {"value": value, "type": type(value).__name__}

    handler.__annotations__ = {"value": annotation}
    handler.__defaults__ = () if default is ... else (default,)
    app.get(path)(handler)


for prefix, marker in [("q", Query("value")), ("h", Header("x-value")), ("c", Cookie("value"))]:
    for typ, default in [(str, "fallback"), (int, 20), (float, 0.0), (bool, False)]:
        scalar(f"/{prefix}/{typ.__name__}", Annotated[typ, marker], default)
    scalar(f"/{prefix}/required", Annotated[str, marker], ...)


@app.get("/stats")
def stats():
    with _lock:
        return {"calls": _calls}


@app.get("/raw")
def raw(request: Request):
    return {"query": request.query, "headers": request.headers}


@app.get("/plain")
def plain():
    return {"ok": True}


class Body(msgspec.Struct):
    name: str


@app.post("/mixed/{item_id}", body=Body)
def mixed(
    limit: Annotated[int, Query("limit")],
    body: Body,
    item_id: int,
    *,
    request_id: Annotated[str, Header("x-request-id")],
    request: Request,
):
    return {
        "limit": limit,
        "name": body.name,
        "id": item_id,
        "request_id": request_id,
        "raw_query": request.query,
        "params": request.params,
        "same_body": request.body is body,
    }


@app.get("/ordered")
def ordered(first: Annotated[int, Header("x-value")], second: Annotated[int, Cookie("value")]):
    return {"first": first, "second": second}


if __name__ == "__main__":
    app.serve(host="127.0.0.1", port=int(os.environ["DEXPOT_EXAMPLE_PORT"]))
