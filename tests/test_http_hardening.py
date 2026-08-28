"""Milestone 1: hostile-input and public-failure real-socket contracts."""

from __future__ import annotations

import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from dexpot import HttpLimits
from dexpot._http import read_request

ROOT = Path(__file__).parent.parent
APP = Path(__file__).parent / "hardened_app.py"
_is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
_GIL_ENABLED = _is_gil_enabled() if _is_gil_enabled is not None else True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(
    port: int,
    *,
    idle_read_seconds: float = 2.0,
    head_read_seconds: float = 3.0,
    body_read_seconds: float = 3.0,
) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["DEXPOT_POOL"] = "1"
    env["DEXPOT_MAX_QUEUE"] = "1"
    env["DEXPOT_TEST_IDLE_SECONDS"] = str(idle_read_seconds)
    env["DEXPOT_TEST_HEAD_SECONDS"] = str(head_read_seconds)
    env["DEXPOT_TEST_BODY_SECONDS"] = str(body_read_seconds)
    process = subprocess.Popen(
        [sys.executable, str(APP), str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"hardened test server exited early\nstdout={stdout!r}\nstderr={stderr!r}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1) as sock:
                sock.sendall(b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
                status, _headers, _body, _rest = _read_response(sock)
                if status == 200:
                    return process
        except OSError:
            time.sleep(0.05)
    process.kill()
    stdout, stderr = process.communicate()
    raise TimeoutError(f"hardened test server not ready\nstdout={stdout!r}\nstderr={stderr!r}")


@pytest.fixture(scope="module")
def hardened_server() -> Iterator[int]:
    port = _free_port()
    process = _start_server(port)
    yield port
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _connect(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.settimeout(2)
    return sock


def _read_response(
    sock: socket.socket, initial: bytes = b""
) -> tuple[int, dict[str, str], bytes, bytes]:
    data = initial
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError(f"connection closed before response head: {data!r}")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split(b" ", 2)[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, value = line.split(b":", 1)
        headers[name.decode("ascii").lower()] = value.strip().decode("latin-1")
    length = int(headers.get("content-length", "0"))
    while len(rest) < length:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before response body")
        rest += chunk
    return status, headers, rest[:length], rest[length:]


def _request(port: int, raw: bytes) -> tuple[int, dict[str, str], bytes]:
    with _connect(port) as sock:
        sock.sendall(raw)
        status, headers, body, _rest = _read_response(sock)
        return status, headers, body


def _json(body: bytes) -> dict[str, object]:
    value = json.loads(body)
    assert isinstance(value, dict)
    return value


def test_http_limits_are_positive_and_immutable() -> None:
    limits = HttpLimits()
    assert limits.request_line_bytes > 0
    assert limits.header_bytes > limits.request_line_bytes
    assert limits.header_count > 0
    assert limits.body_bytes > 0
    assert limits.idle_read_seconds > 0
    assert limits.head_read_seconds > 0
    assert limits.body_read_seconds > 0
    with pytest.raises((AttributeError, TypeError)):
        limits.body_bytes = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="positive"):
        HttpLimits(body_bytes=0)
    for field in ("idle_read_seconds", "head_read_seconds", "body_read_seconds"):
        for non_finite in (math.nan, math.inf, -math.inf):
            with pytest.raises(ValueError, match="finite"):
                HttpLimits(**{field: non_finite})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        HttpLimits(header_count=1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        HttpLimits(body_bytes=True)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"GET /" + b"a" * 130 + b" HTTP/1.1\r\nHost: test\r\n\r\n", 414),
        (
            b"GET /health HTTP/1.1\r\nHost: test\r\n"
            + b"".join(f"X-{i}: 1\r\n".encode() for i in range(9))
            + b"\r\n",
            431,
        ),
        (b"GET /health HTTP/1.1\r\nHost: test\r\nX-Large: " + b"a" * 8200 + b"\r\n\r\n", 431),
        (b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 33\r\n\r\n", 413),
    ],
)
def test_size_limits_fail_closed(hardened_server: int, raw: bytes, expected: int) -> None:
    status, headers, body = _request(hardened_server, raw)
    assert status == expected
    assert headers["connection"] == "close"
    assert "detail" in _json(body)


def test_values_exactly_at_size_limits_succeed(hardened_server: int) -> None:
    request_line = b"GET /" + b"a" * 114 + b" HTTP/1.1"
    assert len(request_line) == 128
    status, _headers, _body = _request(
        hardened_server, request_line + b"\r\nHost: test\r\nConnection: close\r\n\r\n"
    )
    assert status == 404

    head_prefix = b"GET /health HTTP/1.1\r\nHost: test\r\nX-Pad: "
    head = head_prefix + b"a" * (8192 - len(head_prefix))
    assert len(head) == 8192
    status, _headers, body = _request(hardened_server, head + b"\r\n\r\n")
    assert status == 200
    assert _json(body) == {"ok": True}

    count_limited = (
        b"GET /health HTTP/1.1\r\nHost: test\r\n"
        + b"".join(f"X-{index}: 1\r\n".encode() for index in range(7))
        + b"\r\n"
    )
    status, _headers, body = _request(hardened_server, count_limited)
    assert status == 200
    assert _json(body) == {"ok": True}

    body = b'{"value":"xxxxxxxxxxxxxxxxxxxx"}'
    assert len(body) == 32
    status, _headers, response_body = _request(
        hardened_server,
        b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 32\r\n"
        b"Connection: close\r\n\r\n" + body,
    )
    assert status == 200
    assert response_body == body


@pytest.mark.parametrize(
    "framing",
    [
        b"Content-Length: nope\r\n",
        b"Content-Length: -1\r\n",
        b"Content-Length: 1\r\nContent-Length: 2\r\n",
        b"Content-Length: 1, 1\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"Transfer-Encoding: chunked\r\nContent-Length: 4\r\n",
    ],
)
def test_ambiguous_or_unsupported_framing_is_400(hardened_server: int, framing: bytes) -> None:
    status, headers, _body = _request(
        hardened_server,
        b"POST /echo HTTP/1.1\r\nHost: test\r\n" + framing + b"\r\n",
    )
    assert status == 400
    assert headers["connection"] == "close"


def test_identical_duplicate_content_lengths_are_accepted(hardened_server: int) -> None:
    body = b'{"value":""}'
    status, _headers, response_body = _request(
        hardened_server,
        b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 12\r\n"
        b"Content-Length: 12\r\nConnection: close\r\n\r\n" + body,
    )
    assert status == 200
    assert response_body == body


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"BROKEN\r\n\r\n", 400),
        (b"GET health HTTP/1.1\r\nHost: test\r\n\r\n", 400),
        (b"GET /health HTTP/2.0\r\nHost: test\r\n\r\n", 505),
        (b"GET /health HTTP/1.1\r\nBad Header: value\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\n folded\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: one\r\nHost: two\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: te\x00st\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: bad host\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: a,b\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: user@example.com\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: [::1\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: example.com:99999\r\n\r\n", 400),
        (b"GET /health#fragment HTTP/1.1\r\nHost: test\r\n\r\n", 400),
        (b"GET /files/a\\b HTTP/1.1\r\nHost: test\r\n\r\n", 400),
        (b'GET /files/a"b HTTP/1.1\r\nHost: test\r\n\r\n', 400),
        (b"GET /health?value=%ZZ HTTP/1.1\r\nHost: test\r\n\r\n", 400),
        (b"GET /files/%ZZ HTTP/1.1\r\nHost: test\r\n\r\n", 400),
    ],
)
def test_malformed_requests_receive_stable_errors(
    hardened_server: int, raw: bytes, expected: int
) -> None:
    status, headers, body = _request(hardened_server, raw)
    assert status == expected
    assert headers["connection"] == "close"
    assert set(_json(body)) == {"detail"}  # type: ignore[arg-type]


def test_idle_partial_head_times_out(hardened_server: int) -> None:
    with _connect(hardened_server) as sock:
        sock.settimeout(5)
        sock.sendall(b"GET /health HTTP/1.1\r\nHost: test")
        status, headers, _body, _rest = _read_response(sock)
        assert status == 408
        assert headers["connection"] == "close"


def test_slow_drip_head_hits_absolute_deadline() -> None:
    port = _free_port()
    process = _start_server(
        port,
        idle_read_seconds=0.25,
        head_read_seconds=0.35,
        body_read_seconds=1.0,
    )
    try:
        with _connect(port) as sock:
            sock.settimeout(3)
            started = time.monotonic()
            request = b"GET /health HTTP/1.1\r\nHost: test\r\n\r\n"
            for byte in request:
                try:
                    sock.sendall(bytes((byte,)))
                except OSError:
                    break
                time.sleep(0.05)
            status, headers, _body, _rest = _read_response(sock)
            assert status == 408
            assert headers["connection"] == "close"
            assert time.monotonic() - started < 1.5
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=8)


def test_slow_drip_body_hits_absolute_deadline() -> None:
    port = _free_port()
    process = _start_server(
        port,
        idle_read_seconds=0.25,
        head_read_seconds=1.0,
        body_read_seconds=0.35,
    )
    try:
        with _connect(port) as sock:
            sock.settimeout(3)
            sock.sendall(b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 20\r\n\r\n")
            started = time.monotonic()
            for _ in range(20):
                try:
                    sock.sendall(b"x")
                except OSError:
                    break
                time.sleep(0.05)
            status, headers, _body, _rest = _read_response(sock)
            assert status == 408
            assert headers["connection"] == "close"
            assert time.monotonic() - started < 1.5
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=8)


def test_incomplete_body_is_rejected(hardened_server: int) -> None:
    with _connect(hardened_server) as sock:
        sock.sendall(b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 10\r\n\r\n{}")
        sock.shutdown(socket.SHUT_WR)
        status, headers, _body, _rest = _read_response(sock)
        assert status == 400
        assert headers["connection"] == "close"


def test_fragmented_body_accumulates_linearly() -> None:
    class FragmentedSocket:
        def __init__(self, size: int) -> None:
            self.remaining = size
            self.timeouts: list[float] = []

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def recv(self, _size: int) -> bytes:
            if self.remaining <= 0:
                return b""
            self.remaining -= 1
            return b"x"

    size = 400_000
    raw_head = (
        b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: " + str(size).encode() + b"\r\n\r\n"
    )
    started = time.monotonic()
    fragmented = FragmentedSocket(size)
    limits = HttpLimits(body_bytes=size, body_read_seconds=10)
    request, remaining = read_request(
        fragmented,  # type: ignore[arg-type]
        raw_head,
        limits,
    )
    elapsed = time.monotonic() - started
    assert len(request.body) == size
    assert remaining == b""
    assert fragmented.timeouts[-1] == limits.idle_read_seconds
    assert elapsed < 2.0


def test_huge_content_length_is_deterministically_413(hardened_server: int) -> None:
    huge = b"9" * 5000
    status, _headers, body = _request(
        hardened_server,
        b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: "
        + huge
        + b"\r\nConnection: close\r\n\r\n",
    )
    assert status == 413
    assert _json(body) == {"detail": "request body too large"}


def test_404_and_405_are_distinct_with_allow(hardened_server: int) -> None:
    missing = _request(
        hardened_server, b"GET /missing HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"
    )
    assert missing[0] == 404

    status, headers, body = _request(
        hardened_server, b"POST /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"
    )
    assert status == 405
    assert headers["allow"] == "GET"
    assert _json(body) == {"detail": "method not allowed"}

    status, headers, _body = _request(
        hardened_server, b"get /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"
    )
    assert status == 405
    assert headers["allow"] == "GET"


def test_percent_decoding_and_strict_slash_policy(hardened_server: int) -> None:
    status, _headers, body = _request(
        hardened_server,
        b"GET /files/hello%20world HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 200
    assert _json(body) == {"name": "hello world"}

    for path in (b"/files/a%2Fb", b"/files//name", b"/files/name/"):
        status, _headers, _body = _request(
            hardened_server,
            b"GET " + path + b" HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
        )
        assert status == 404


@pytest.mark.parametrize(
    "host",
    [b"example.com", b"example.com:8080", b"127.0.0.1", b"[::1]", b"[v1.fe]:80"],
)
def test_valid_host_authorities_are_accepted(hardened_server: int, host: bytes) -> None:
    status, _headers, body = _request(
        hardened_server,
        b"GET /health HTTP/1.1\r\nHost: " + host + b"\r\nConnection: close\r\n\r\n",
    )
    assert status == 200
    assert _json(body) == {"ok": True}


def test_valid_origin_form_path_and_query_characters(hardened_server: int) -> None:
    status, _headers, body = _request(
        hardened_server,
        b"GET /files/a!$&'()*+,:;=@._~-?x=a/b?c&d=e HTTP/1.1\r\n"
        b"Host: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 200
    assert _json(body) == {"name": "a!$&'()*+,:;=@._~-"}


def test_http_version_keep_alive_policy_and_pipelining(hardened_server: int) -> None:
    with _connect(hardened_server) as sock:
        sock.sendall(
            b"GET /health HTTP/1.1\r\nHost: test\r\n\r\n"
            b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"
        )
        first_status, first_headers, _first_body, rest = _read_response(sock)
        second_status, second_headers, _second_body, _rest = _read_response(sock, rest)
        assert first_status == second_status == 200
        assert first_headers["connection"] == "keep-alive"
        assert second_headers["connection"] == "close"
        assert sock.recv(1) == b""

    with _connect(hardened_server) as sock:
        sock.sendall(b"GET /health HTTP/1.0\r\n\r\n")
        status, headers, _body, _rest = _read_response(sock)
        assert status == 200
        assert headers["connection"] == "close"
        assert sock.recv(1) == b""

    with _connect(hardened_server) as sock:
        sock.sendall(
            b"GET /health HTTP/1.0\r\nConnection: keep-alive\r\n\r\n"
            b"GET /health HTTP/1.0\r\nConnection: close\r\n\r\n"
        )
        first_status, first_headers, _body, rest = _read_response(sock)
        second_status, second_headers, _body, _rest = _read_response(sock, rest)
        assert first_status == second_status == 200
        assert first_headers["connection"] == "keep-alive"
        assert second_headers["connection"] == "close"

    with _connect(hardened_server) as sock:
        sock.sendall(
            b"GET /health HTTP/1.0\r\nConnection: keep-alive, close\r\n\r\n"
            b"GET /health HTTP/1.0\r\n\r\n"
        )
        status, headers, _body, rest = _read_response(sock)
        assert status == 200
        assert headers["connection"] == "close"
        assert rest == b""
        assert sock.recv(1) == b""


def test_http_10_parse_failure_uses_http_10_status_line(hardened_server: int) -> None:
    with _connect(hardened_server) as sock:
        sock.sendall(b"POST /echo HTTP/1.0\r\nContent-Length: 10\r\n\r\n{}")
        sock.shutdown(socket.SHUT_WR)
        data = sock.recv(4096)
        assert data.startswith(b"HTTP/1.0 400 Bad Request\r\n")

    with _connect(hardened_server) as sock:
        sock.sendall(b"GET health HTTP/1.0\r\n\r\n")
        data = sock.recv(4096)
        assert data.startswith(b"HTTP/1.0 400 Bad Request\r\n")


def test_handler_exception_does_not_leak(hardened_server: int) -> None:
    status, _headers, body = _request(
        hardened_server,
        b"GET /boom HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 500
    assert _json(body) == {"detail": "internal server error"}
    assert b"private-token" not in body
    assert b"RuntimeError" not in body


@pytest.mark.parametrize("path", [b"/bad-status-string", b"/bad-status-range"])
def test_invalid_handler_status_becomes_sanitized_500(hardened_server: int, path: bytes) -> None:
    status, headers, body = _request(
        hardened_server,
        b"GET " + path + b" HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 500
    assert headers["connection"] == "close"
    assert _json(body) == {"detail": "internal server error"}


def test_204_response_has_no_body(hardened_server: int) -> None:
    status, headers, body = _request(
        hardened_server,
        b"GET /no-content HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 204
    assert headers["content-length"] == "0"
    assert body == b""


def test_disconnects_do_not_break_subsequent_requests(hardened_server: int) -> None:
    for payload in (
        b"GET /health HTTP/1.1\r\n",
        b"POST /echo HTTP/1.1\r\nHost: test\r\nContent-Length: 20\r\n\r\n{}",
    ):
        with _connect(hardened_server) as sock:
            sock.sendall(payload)
    time.sleep(0.05)
    status, _headers, body = _request(
        hardened_server,
        b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    )
    assert status == 200
    assert _json(body) == {"ok": True}


@pytest.mark.skipif(not _GIL_ENABLED, reason="free-threaded mode has no framework work queue")
def test_saturation_still_returns_503(hardened_server: int) -> None:
    first = _connect(hardened_server)
    second: socket.socket | None = None
    third: socket.socket | None = None
    try:
        first.sendall(b"GET /health HTTP/1.1\r\nHost: test")
        time.sleep(0.2)
        second = _connect(hardened_server)
        second.sendall(b"GET /health HTTP/1.1\r\nHost: test")
        time.sleep(0.2)
        third = _connect(hardened_server)
        third.sendall(b"GET /health HTTP/1.1\r\nHost: test\r\n\r\n")
        status, headers, body, _rest = _read_response(third)
        assert status == 503
        assert headers["connection"] == "close"
        assert _json(body) == {"detail": "overloaded"}
    finally:
        first.close()
        if second is not None:
            second.close()
        if third is not None:
            third.close()


@pytest.mark.skipif(_GIL_ENABLED, reason="GIL mode uses bounded admission instead")
def test_free_threaded_admission_does_not_use_gil_queue(hardened_server: int) -> None:
    slow = [_connect(hardened_server) for _ in range(8)]
    try:
        for sock in slow:
            sock.sendall(b"GET /health HTTP/1.1\r\nHost: test")
        status, _headers, body = _request(
            hardened_server,
            b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
        )
        assert status == 200
        assert _json(body) == {"ok": True}
    finally:
        for sock in slow:
            sock.close()


def test_sigterm_interrupts_slow_client_and_respects_drain_deadline() -> None:
    port = _free_port()
    process = _start_server(
        port,
        idle_read_seconds=30.0,
        head_read_seconds=30.0,
        body_read_seconds=30.0,
    )
    slow = _connect(port)
    try:
        slow.sendall(b"GET /health HTTP/1.1\r\nHost: test")
        time.sleep(0.1)
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=7) == 0
        elapsed = time.monotonic() - started
        assert 4.5 <= elapsed < 6.5
    finally:
        slow.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
