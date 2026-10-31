"""Nested checked-response example exercised through its real HTTP socket."""

from __future__ import annotations

import contextlib
import http.client
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "nested_responses.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _server() -> Iterator[int]:
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["DEXPOT_EXAMPLE_HOST"] = "127.0.0.1"
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"example exited: {stdout!r} {stderr!r}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        stdout, stderr = process.communicate()
        raise TimeoutError(f"example did not start: {stdout!r} {stderr!r}")
    try:
        yield port
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        assert process.returncode == 0


def _request(connection: http.client.HTTPConnection, path: str) -> tuple[int, bytes]:
    connection.request("GET", path)
    response = connection.getresponse()
    return response.status, response.read()


def test_nested_schema_projects_private_fields_and_uses_defaults() -> None:
    with _server() as port:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            status, body = _request(connection, "/catalog")
        finally:
            connection.close()
    assert status == 200
    assert body == b'{"items":[{"name":"tea","quantity":1,"price":2.5}],"note":"ready"}'


def test_malformed_and_nonfinite_nested_responses_are_sanitized_and_connection_recovers() -> None:
    with _server() as port:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            for path in ("/invalid", "/nonfinite"):
                status, body = _request(connection, path)
                assert status == 500
                assert body == b'{"detail":"internal server error"}'
            status, body = _request(connection, "/catalog")
        finally:
            connection.close()
    assert status == 200
    assert body == b'{"items":[{"name":"tea","quantity":1,"price":2.5}],"note":"ready"}'
