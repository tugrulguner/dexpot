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
        head_read_seconds=float(os.environ.get("DEXPOT_TEST_HEAD_SECONDS", "1.0")),
        body_read_seconds=float(os.environ.get("DEXPOT_TEST_BODY_SECONDS", "1.0")),
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


@app.get("/bad-status-string")
def bad_status_string() -> tuple[str, dict[str, bool]]:
    return "200", {"ok": True}


@app.get("/bad-status-range")
def bad_status_range() -> tuple[int, dict[str, bool]]:
    return 1000, {"ok": True}


@app.get("/no-content")
def no_content() -> tuple[int, dict[str, bool]]:
    return 204, {"ok": True}


if __name__ == "__main__":
    app.serve(host="127.0.0.1", port=int(sys.argv[1]))
