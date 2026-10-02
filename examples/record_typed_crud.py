"""Record the typed CRUD example's actual local HTTP responses as JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "typed_crud.py"
DEFAULT_OUTPUT = ROOT / "website" / "src" / "content" / "docs" / "data" / "typed-crud-capture.json"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def record() -> dict[str, Any]:
    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["DEXPOT_EXAMPLE_HOST"] = "127.0.0.1"
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    process = subprocess.Popen([sys.executable, str(SOURCE)], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"typed CRUD example exited with {process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise TimeoutError("typed CRUD example did not start")

        requests = [
            ("GET", "/items/1", None),
            ("POST", "/items", {"name": "keyboard", "price": 79.0}),
            ("PUT", "/items/2", {"name": "keyboard-pro", "price": 99.0}),
            ("DELETE", "/items/2", None),
            ("GET", "/items/2", None),
        ]
        steps = []
        with httpx.Client(base_url=base) as client:
            for method, path, body in requests:
                response = client.request(method, path, json=body)
                steps.append(
                    {
                        "method": method,
                        "path": path,
                        "request": body,
                        "status": response.status_code,
                        "response": response.json(),
                    }
                )
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        from dexpot import __version__

        return {
            "mode": "recorded-local-http-execution",
            "source": {
                "file": "examples/typed_crud.py",
                "commit": git_commit,
                "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "version": __version__,
            },
            "steps": steps,
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    capture = record()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(capture, indent=2) + "\n")
    print(f"Recorded {len(capture['steps'])} real HTTP steps in {args.output}")


if __name__ == "__main__":
    main()
