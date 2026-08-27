from __future__ import annotations

import os
import sys

import msgspec

from dexpot import Dex, HttpLimits


class Echo(msgspec.Struct):
    value: str


app = Dex(
    limits=HttpLimits(
        request_line_bytes=128,
        header_bytes=8192,
        header_count=8,
        body_bytes=32,
        idle_read_seconds=float(os.environ.get("DEXPOT_TEST_IDLE_SECONDS", "0.25")),
    )
)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/echo", body=Echo)
def echo(item: Echo) -> Echo:
    return item


@app.get("/files/{name}")
def file_name(name: str) -> dict[str, str]:
    return {"name": name}


@app.get("/boom")
def boom() -> dict[str, bool]:
    raise RuntimeError("private-token-must-not-leak")


if __name__ == "__main__":
    app.serve(host="127.0.0.1", port=int(sys.argv[1]))
