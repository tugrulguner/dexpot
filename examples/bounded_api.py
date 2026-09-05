"""Runnable bounded API: custom limits and fail-closed HTTP behavior."""

from __future__ import annotations

import os

import msgspec

from dexpot import Dex, HttpLimits

app = Dex(
    limits=HttpLimits(
        request_line_bytes=2 * 1024,
        header_bytes=8 * 1024,
        header_count=32,
        body_bytes=64,
        idle_read_seconds=2.0,
        head_read_seconds=5.0,
        body_read_seconds=5.0,
    )
)


class Message(msgspec.Struct):
    text: str


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/echo", body=Message, response=Message)
def echo(message: Message) -> Message:
    return message


def register_context() -> None:
    from dexpot import Request as Context

    @app.get("/context", annotation_locals={"Context": Context})
    def context(request: Context) -> dict[str, str]:
        return {"method": request.method}


register_context()


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
