"""A completed native I/O return must not pin the synchronous handler owner."""

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
GIL_ENABLED = getattr(sys, "_is_gil_enabled", lambda: True)()


@pytest.mark.skipif(not GIL_ENABLED, reason="GIL-only I/O ownership repair")
@pytest.mark.skipif(sys.platform == "win32", reason="Windows retains its incumbent pool backend")
@pytest.mark.parametrize("boundary", ["send", "recv"])
def test_next_request_progresses_when_worker_socket_return_is_suspended(boundary):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHON_GIL", "PYTHONPATH")}
    env.update(
        PYTHONPATH=os.environ.get("SOCKET_PROGRESS_SOURCE", str(ROOT / "src")),
        DEXPOT_POOL="1",
        DEXPOT_MAX_QUEUE="1",
        DEXPOT_WORKERS="1",
        DEXPOT_HTTP_PARSER="python",
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/gil_io_stall_app.py"), str(port), boundary],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stdin is not None
    ready = threading.Event()
    stream = process.stdout

    def observe_startup():
        try:
            for line in stream:
                if b"dexpot serving on" in line:
                    ready.set()
                    return
        except (OSError, ValueError):
            return

    observer = threading.Thread(target=observe_startup, daemon=True)
    observer.start()
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        assert ready.wait(5), "controlled test server did not start"
        client.request("GET", "/")
        first = client.getresponse()
        assert first.status == 200
        first_body = json.loads(first.read())
        assert first_body["count"] == 1
        progressed = False
        second_body = None
        try:
            client.request("GET", "/")
            second = client.getresponse()
            second_body = json.loads(second.read())
            progressed = second.status == 200
        except TimeoutError:
            pass
        assert progressed, (
            "next request was pinned behind a suspended completed worker socket return"
        )
        assert second_body is not None and second_body["count"] == 2
        assert second_body["handler_thread"] == first_body["handler_thread"], (
            "keep-alive handler ownership changed"
        )
        if sys.platform == "darwin":
            assert second_body["write_rpcs"] == 0, "Darwin serving still uses write RPC replies"
    finally:
        client.close()
        if process.poll() is None:
            process.stdin.write(b"x")
            process.stdin.flush()
            process.send_signal(signal.SIGTERM)
        observer.join(2)
        try:
            process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=2)
