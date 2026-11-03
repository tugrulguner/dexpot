from __future__ import annotations

import socket
import subprocess
import sys
import time

import httpx
import pytest


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def typed_server():
    port = _port()
    code = f"""from typing import Annotated
from dexpot import Dex, Query
app=Dex()
@app.get("/value")
def value(limit: Annotated[int, Query("limit")] = 3): return {{"limit": limit}}
app.serve("127.0.0.1", {port})"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"fixture exited: {proc.communicate()!r}")
        try:
            if httpx.get(url + "/value?limit=8", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        proc.terminate()
        proc.communicate(timeout=5)
        pytest.fail("server did not start")
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=3)
            pytest.fail("server did not stop")


def test_query_integer_binding_over_real_http(typed_server):
    response = httpx.get(typed_server + "/value?limit=8")
    assert response.status_code == 200
    assert response.json() == {"limit": 8}


def test_missing_query_uses_default_over_real_http(typed_server):
    assert httpx.get(typed_server + "/value").json() == {"limit": 3}
