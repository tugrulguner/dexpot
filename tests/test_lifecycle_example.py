from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "lifecycle.py"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(port: int, method: str, path: str, body: bytes | None = None):
    request = Request(f"http://127.0.0.1:{port}{path}", data=body, method=method)
    with urlopen(request, timeout=2) as response:
        return response.status, response.read()


def _start(tmp_path: Path, **extra_env: str):
    port = _port()
    events = tmp_path / "events.jsonl"
    env = os.environ.copy()
    env.update(DEXPOT_EXAMPLE_PORT=str(port), DEXPOT_EXAMPLE_EVENTS=str(events), **extra_env)
    proc = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, port, events


def _wait_ready(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(
                f"example exited early: {proc.stdout.read() if proc.stdout else ''}"
            )
        try:
            if _request(port, "GET", "/health") == (200, b'{"ok":true}'):
                return
        except (OSError, URLError):
            time.sleep(0.05)
    raise AssertionError("example did not become ready")


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
        raise AssertionError("example did not stop after SIGTERM") from None


def _events(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_http_cache_is_shared_and_cleared_on_sigterm(tmp_path: Path) -> None:
    proc, port, events = _start(tmp_path)
    try:
        _wait_ready(proc, port)
        assert _request(port, "GET", "/health") == (200, b'{"ok":true}')
        assert _request(port, "PUT", "/cache/example", b'{"value":"stored"}') == (
            200,
            b'{"key":"example","value":"stored"}',
        )
        for invalid in (b'{"value":7}', b"not-json", b"{}"):
            try:
                _request(port, "PUT", "/cache/example", invalid)
            except HTTPError as error:
                assert error.code == 422
            else:
                raise AssertionError("invalid input reached the cache write")
        assert _request(port, "GET", "/cache/example") == (
            200,
            b'{"key":"example","value":"stored"}',
        )
    finally:
        _stop(proc)
    assert proc.returncode == 0
    lifecycle = [event["event"] for event in _events(events)]
    assert lifecycle == ["acquire:cache", "enter:check", "exit:check", "release:cache"]


def test_startup_failure_rolls_back_before_listener_starts(tmp_path: Path) -> None:
    proc, port, events = _start(tmp_path, DEXPOT_EXAMPLE_FAIL_STARTUP="check")
    try:
        output = proc.communicate(timeout=8)[0]
        assert proc.returncode != 0
        assert "dexpot serving on" not in output
        try:
            _request(port, "GET", "/health")
        except (OSError, URLError):
            pass
        else:
            raise AssertionError("listener accepted traffic after failed startup")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
    lifecycle = [event["event"] for event in _events(events)]
    assert lifecycle == ["acquire:cache", "enter:check", "exit:check", "release:cache"]
