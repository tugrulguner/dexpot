"""Run every public example through dexpot's real CLI-independent HTTP surface."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
EXPECTED_EXAMPLES = {"bounded_api.py", "minimal.py", "typed_crud.py"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _run_example(filename: str) -> Iterator[str]:
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["DEXPOT_EXAMPLE_HOST"] = "127.0.0.1"
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLES / filename)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"{filename} exited during startup\nstdout={stdout!r}\nstderr={stderr!r}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        stdout, stderr = process.communicate()
        raise TimeoutError(f"{filename} did not start\nstdout={stdout!r}\nstderr={stderr!r}")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        assert process.returncode == 0


def test_example_inventory_is_intentional_and_compiles() -> None:
    examples = {path.name for path in EXAMPLES.glob("*.py")}
    assert examples == EXPECTED_EXAMPLES
    for filename in sorted(examples):
        source = (EXAMPLES / filename).read_text()
        compile(source, str(EXAMPLES / filename), "exec")


def test_minimal_example_serves_typed_path_response() -> None:
    with _run_example("minimal.py") as base:
        response = httpx.get(f"{base}/items/7")
    assert response.status_code == 200
    assert response.json() == {"id": 7, "name": "item-7", "price": 7.0}


def test_typed_crud_example_runs_complete_lifecycle() -> None:
    with _run_example("typed_crud.py") as base:
        initial = httpx.get(f"{base}/items/1")
        created = httpx.post(f"{base}/items", json={"name": "keyboard", "price": 79.0})
        replaced = httpx.put(f"{base}/items/2", json={"name": "keyboard-pro", "price": 99.0})
        deleted = httpx.delete(f"{base}/items/2")
        missing = httpx.get(f"{base}/items/2")

    assert initial.json() == {"id": 1, "name": "starter", "price": 9.99}
    assert created.status_code == 201
    assert created.json() == {"id": 2, "name": "keyboard", "price": 79.0}
    assert replaced.json() == {"id": 2, "name": "keyboard-pro", "price": 99.0}
    assert deleted.json() == {"deleted": 2}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "item not found"}


def test_bounded_api_example_validates_success_and_failure_paths() -> None:
    with _run_example("bounded_api.py") as base:
        health = httpx.get(f"{base}/health")
        echoed = httpx.post(f"{base}/echo", json={"text": "hello"})
        malformed = httpx.post(
            f"{base}/echo",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        oversized = httpx.post(f"{base}/echo", json={"text": "x" * 100})
        wrong_method = httpx.post(f"{base}/health")

    assert health.json() == {"ok": True}
    assert echoed.json() == {"text": "hello"}
    assert malformed.status_code == 422
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "request body too large"}
    assert wrong_method.status_code == 405
    assert wrong_method.headers["allow"] == "GET"
