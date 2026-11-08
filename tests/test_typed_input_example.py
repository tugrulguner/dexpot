"""Run the released scalar-input example through the real socket server."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "typed_inputs.py"


@contextmanager
def _server() -> Iterator[str]:
    assert EXAMPLE.is_file(), "typed source binding needs a runnable example"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    env["DEXPOT_EXAMPLE_HOST"] = "127.0.0.1"
    env["DEXPOT_WORKERS"] = "1"
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    started = False
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.communicate()[0]
                raise AssertionError(f"typed-input example exited before readiness: {output!r}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    started = True
                    break
            except OSError:
                time.sleep(0.05)
        assert started, "typed-input example did not become ready"
        yield f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
            raise AssertionError("typed-input example did not shut down") from None
        if started:
            assert process.returncode == 0


@pytest.mark.parametrize("query", ["limit=1&limit=2", "limit=1&limit=1", "limit=1&%6cimit=1"])
def test_example_rejects_repeated_scalars_without_first_or_last_selection(query: str) -> None:
    with _server() as base, httpx.Client(base_url=base, trust_env=False) as client:
        single = client.get("/items/drinks?limit=1", headers={"X-Request-ID": "control"})
        repeated = client.get(f"/items/drinks?{query}", headers={"X-Request-ID": "repeated"})
        recovery = client.get("/items/drinks?limit=2", headers={"X-Request-ID": "recovery"})
    assert single.status_code == 200 and single.json()["limit"] == 1
    assert repeated.status_code == 422
    assert repeated.json() == {"detail": "query parameter 'limit': repeated"}
    assert recovery.status_code == 200 and recovery.json()["limit"] == 2


def test_example_binds_query_header_cookie_and_defaults() -> None:
    with _server() as base, httpx.Client(base_url=base, trust_env=False) as client:
        default = client.get("/items/drinks", headers={"X-Request-ID": "default"})
        filtered = client.get(
            "/items/drinks?limit=1&min_price=3&include_archived=false",
            headers={"X-Request-ID": "filtered", "Cookie": "theme=dark"},
        )
    assert default.status_code == 200
    payload = default.json()
    assert [item["id"] for item in payload["items"]] == [1, 2]
    assert payload["limit"] == 20 and payload["offset"] == 0
    assert payload["min_price"] == 0.0 and payload["include_archived"] is False
    assert payload["request_id"] == "default" and payload["theme"] == "light"
    assert filtered.status_code == 200
    payload = filtered.json()
    assert [item["id"] for item in payload["items"]] == [2]
    assert payload["limit"] == 1 and payload["min_price"] == 3.0
    assert payload["include_archived"] is False
    assert payload["request_id"] == "filtered" and payload["theme"] == "dark"
