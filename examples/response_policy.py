"""Checked JSON, custom headers, explicit raw/empty output, and legacy tuples."""

from __future__ import annotations

import os

import msgspec

from dexpot import Dex, RawResponse, Response

app = Dex()


class Public(msgspec.Struct):
    name: str


@app.get("/public", response=Public)
def public() -> Response:
    return Response(
        {"name": "alice", "secret": "filtered"},
        status=201,
        headers=[("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")],
    )


@app.get("/invalid", response=Public)
def invalid() -> dict[str, int]:
    # Deliberate invalid output: the client receives only a sanitized 500.
    return {"name": 42}


@app.get("/raw")
def raw() -> RawResponse:
    return RawResponse(b"hello\n", content_type="text/plain; charset=utf-8")


@app.get("/empty", response=Public)
def empty() -> Response:
    return Response(status=204)


@app.get("/tuple", response=Public)
def legacy() -> tuple[int, dict[str, str]]:
    return 202, {"name": "legacy", "secret": "filtered"}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
