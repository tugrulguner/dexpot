"""Bounded blocking HTTP calls to a local teaching upstream.

Run ``uv run python examples/outbound_io.py``. This is not production transport
infrastructure. It uses only fixed allowlisted loopback routes and no credentials.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import msgspec

from dexpot import Dex
from dexpot.app import HTTPError


class LocalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        if self.path == "/slow":
            time.sleep(0.35)
        if self.path == "/error":
            self.send_response(503)
            body = b"upstream detail must not escape"
        elif self.path == "/malformed":
            self.send_response(200)
            body = b"not json"
        elif self.path == "/oversized":
            self.send_response(200)
            body = json.dumps({"message": "x" * 5000}).encode()
        else:
            self.send_response(200)
            body = b'{"message":"local upstream"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class LocalServer(HTTPServer):
    allow_reuse_address = True


class OutboundPool:
    def __init__(self, port: int):
        self._port = port
        self._available: list[http.client.HTTPConnection] = [
            http.client.HTTPConnection("127.0.0.1", port, timeout=0.12)
        ]
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def lease(self) -> Iterator[http.client.HTTPConnection]:
        with self._lock:
            if not self._available:
                raise HTTPError(503, "outbound capacity exhausted")
            connection = self._available.pop()
        broken = False
        try:
            yield connection
        except (OSError, http.client.HTTPException, ValueError):
            broken = True
            raise
        finally:
            if broken:
                connection.close()
                connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=0.12)
            with self._lock:
                self._available.append(connection)

    def close(self) -> None:
        with self._lock:
            connections, self._available = self._available, []
        for connection in connections:
            connection.close()


app = Dex()
state: dict[str, OutboundPool] = {}


@contextlib.contextmanager
def resources() -> Iterator[None]:
    fixture = LocalServer(("127.0.0.1", 0), LocalHandler)
    thread: threading.Thread | None = None
    started = False
    pool: OutboundPool | None = None
    try:
        thread = threading.Thread(
            target=lambda: fixture.serve_forever(poll_interval=0.05), name="local-upstream"
        )
        thread.start()
        started = True
        pool = OutboundPool(fixture.server_port)
        state["pool"] = pool
        yield
    finally:
        state.pop("pool", None)
        try:
            if pool is not None:
                pool.close()
        finally:
            try:
                if started:
                    fixture.shutdown()
            finally:
                fixture.server_close()
                if started and thread is not None:
                    thread.join(timeout=1)
                    if thread.is_alive():
                        raise RuntimeError("local upstream did not stop")


app.lifespan(resources)


class Result(msgspec.Struct):
    status: int
    body: dict[str, str]


def _fetch(path: str) -> tuple[int, dict[str, str]]:
    try:
        with state["pool"].lease() as connection:
            connection.request("GET", path)
            with connection.getresponse() as response:
                body = response.read(4097)
                if len(body) > 4096:
                    raise ValueError("upstream response too large")
                if response.status != 200:
                    raise ValueError("upstream returned error")
                decoded = json.loads(body)
                if not isinstance(decoded, dict) or not isinstance(decoded.get("message"), str):
                    raise ValueError("invalid upstream response")
                return response.status, {"message": decoded["message"]}
    except TimeoutError:
        raise HTTPError(504, "upstream timeout") from None
    except (OSError, http.client.HTTPException, ValueError, json.JSONDecodeError):
        raise HTTPError(502, "upstream unavailable") from None


@app.get("/ok", response=Result)
def ok() -> dict[str, object]:
    status, body = _fetch("/ok")
    return {"status": status, "body": body}


@app.get("/upstream-error", response=None)
def upstream_error() -> tuple[int, dict[str, str]]:
    _fetch("/error")
    return 200, {"detail": "unreachable"}


@app.get("/malformed", response=None)
def malformed() -> tuple[int, dict[str, str]]:
    _fetch("/malformed")
    return 200, {"detail": "unreachable"}


@app.get("/slow", response=None)
def slow() -> tuple[int, dict[str, str]]:
    _fetch("/slow")
    return 200, {"detail": "unreachable"}


@app.get("/oversized", response=None)
def oversized() -> tuple[int, dict[str, str]]:
    _fetch("/oversized")
    return 200, {"detail": "unreachable"}


@app.get("/hold", response=None)
def hold() -> dict[str, bool]:
    with state["pool"].lease():
        time.sleep(3.0)
    return {"ok": True}


@app.get("/capacity")
def capacity() -> dict[str, int]:
    pool = state["pool"]
    with pool._lock:
        return {"available": len(pool._available), "limit": 1}


if __name__ == "__main__":
    import os

    os.environ["DEXPOT_WORKERS"] = "1"
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
