"""Smoke an installed dexpot distribution and every runnable example.

Run this with the Python interpreter from a clean environment containing the
built distribution. The example subprocesses start outside the repository and
with PYTHONPATH removed, so imports must resolve from that installed artifact.
"""

from __future__ import annotations

import http.client
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
EXPECTED_EXAMPLES = {"bounded_api.py", "minimal.py", "typed_crud.py"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _serve(example: Path) -> Iterator[int]:
    port = _free_port()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["DEXPOT_EXAMPLE_HOST"] = "127.0.0.1"
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    with tempfile.TemporaryDirectory(prefix="dexpot-example-") as cwd:
        process = subprocess.Popen(
            [sys.executable, str(example)],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(
                    f"{example.name} exited during startup\nstdout={stdout!r}\nstderr={stderr!r}"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            process.kill()
            stdout, stderr = process.communicate()
            raise TimeoutError(
                f"{example.name} did not start\nstdout={stdout!r}\nstderr={stderr!r}"
            )

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
            if process.returncode != 0:
                stdout, stderr = process.communicate()
                raise RuntimeError(
                    f"{example.name} exited {process.returncode}\n"
                    f"stdout={stdout!r}\nstderr={stderr!r}"
                )


def _request(
    port: int,
    method: str,
    path: str,
    payload: object | None = None,
    *,
    raw: bytes | None = None,
) -> tuple[int, dict[str, str], Any]:
    body: bytes | None = raw
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        headers["Content-Type"] = "application/json"

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
    finally:
        connection.close()
    decoded = json.loads(data) if data else None
    return response.status, response_headers, decoded


def _check_cli() -> None:
    version = importlib.metadata.version("dexpot")
    executable = Path(sys.executable).with_name("dexpot")
    if os.name == "nt":
        executable = executable.with_suffix(".exe")
    if not executable.is_file():
        raise AssertionError(f"installed console script not found: {executable}")
    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == f"dexpot {version}"


def _check_minimal(path: Path) -> None:
    with _serve(path) as port:
        status, _headers, body = _request(port, "GET", "/items/7")
    assert status == 200
    assert body == {"id": 7, "name": "item-7", "price": 7.0}


def _check_crud(path: Path) -> None:
    with _serve(path) as port:
        assert _request(port, "GET", "/items/1")[2] == {
            "id": 1,
            "name": "starter",
            "price": 9.99,
        }
        created = _request(port, "POST", "/items", {"name": "keyboard", "price": 79.0})
        assert created[0] == 201
        assert created[2] == {"id": 2, "name": "keyboard", "price": 79.0}
        replaced = _request(
            port,
            "PUT",
            "/items/2",
            {"name": "keyboard-pro", "price": 99.0},
        )
        assert replaced[2] == {"id": 2, "name": "keyboard-pro", "price": 99.0}
        assert _request(port, "DELETE", "/items/2")[2] == {"deleted": 2}
        missing = _request(port, "GET", "/items/2")
        assert missing[0] == 404
        assert missing[2] == {"detail": "item not found"}


def _check_bounded(path: Path) -> None:
    with _serve(path) as port:
        assert _request(port, "GET", "/health")[2] == {"ok": True}
        assert _request(port, "POST", "/echo", {"text": "hello"})[2] == {"text": "hello"}
        assert _request(port, "POST", "/echo", raw=b"not-json")[0] == 422
        oversized = _request(port, "POST", "/echo", {"text": "x" * 100})
        assert oversized[0] == 413
        assert oversized[2] == {"detail": "request body too large"}
        wrong_method = _request(port, "POST", "/health")
        assert wrong_method[0] == 405
        assert wrong_method[1]["allow"] == "GET"


def main() -> None:
    discovered = {path.name for path in EXAMPLES.glob("*.py")}
    assert discovered == EXPECTED_EXAMPLES, discovered

    _check_cli()
    _check_minimal(EXAMPLES / "minimal.py")
    _check_crud(EXAMPLES / "typed_crud.py")
    _check_bounded(EXAMPLES / "bounded_api.py")
    print(
        f"installed dexpot {importlib.metadata.version('dexpot')} passed CLI and "
        f"{len(discovered)} example smokes"
    )


if __name__ == "__main__":
    main()
