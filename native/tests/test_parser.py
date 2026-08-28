from __future__ import annotations

import random
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from dexpot._http import HTTPParseError, _parse_headers, _validate_request_line
from dexpot_native import PARSER_API_VERSION
from dexpot_native import _parser as native_parser

DEFAULTS = (8192, 65536, 100, 16 * 1024 * 1024)


def test_parser_api_version_is_explicit() -> None:
    assert PARSER_API_VERSION == 1


def python_parse_head(
    head: bytes,
    request_line_limit: int = DEFAULTS[0],
    header_bytes_limit: int = DEFAULTS[1],
    header_count_limit: int = DEFAULTS[2],
    body_limit: int = DEFAULTS[3],
) -> tuple[str, bytes, str, dict[str, str], int, bool]:
    if len(head) > header_bytes_limit:
        raise HTTPParseError(431, "request headers too large")
    lines = head.split(b"\r\n")
    method, target, version = _validate_request_line(lines[0], request_line_limit)
    try:
        headers, content_length = _parse_headers(lines[1:], header_count_limit, body_limit)
    except HTTPParseError as exc:
        raise exc.with_version(version) from None
    if version == "HTTP/1.1" and not headers.get("host", "").strip():
        raise HTTPParseError(400, "missing host header", version)
    connection_tokens = {
        token.strip().lower() for token in headers.get("connection", "").split(",") if token.strip()
    }
    keep_alive = "close" not in connection_tokens and (
        version == "HTTP/1.1" or "keep-alive" in connection_tokens
    )
    return method, target, version, headers, content_length, keep_alive


def native_parse_head(
    head: bytes,
    request_line_limit: int = DEFAULTS[0],
    header_bytes_limit: int = DEFAULTS[1],
    header_count_limit: int = DEFAULTS[2],
    body_limit: int = DEFAULTS[3],
) -> tuple[str, bytes, str, dict[str, str], int, bool]:
    return native_parser.parse_head(
        head,
        request_line_limit,
        header_bytes_limit,
        header_count_limit,
        body_limit,
    )


def outcome(
    parser: Callable[..., tuple[str, bytes, str, dict[str, str], int, bool]],
    head: bytes,
    limits: tuple[int, int, int, int] = DEFAULTS,
) -> tuple[str, Any]:
    try:
        return "ok", parser(head, *limits)
    except HTTPParseError as exc:
        return "error", (exc.status, exc.detail, exc.version)
    except ValueError as exc:
        return "error", exc.args


def assert_parity(head: bytes, limits: tuple[int, int, int, int] = DEFAULTS) -> None:
    assert outcome(native_parse_head, head, limits) == outcome(python_parse_head, head, limits)


def test_parse_head_returns_compact_routing_metadata() -> None:
    data = b"GET /items/42?view=full HTTP/1.1\r\nHost: example.com"
    parsed = native_parse_head(data)
    assert parsed == (
        "GET",
        b"/items/42?view=full",
        "HTTP/1.1",
        {"host": "example.com"},
        0,
        True,
    )


def test_mutable_input_is_rejected() -> None:
    head = bytearray(b"GET / HTTP/1.1\r\nHost: example.com")
    with pytest.raises(TypeError):
        native_parser.parse_head(head, *DEFAULTS)  # type: ignore[arg-type]


CORPUS = [
    b"GET / HTTP/1.1\r\nHost: example.com",
    b"get /items/42 HTTP/1.1\r\nHost: example.com\r\nConnection: CLOSE",
    b"OPTIONS / HTTP/1.0\r\nConnection: keep-alive",
    b"M-SEARCH / HTTP/1.1\r\nHost: example.com",
    b"POST /items HTTP/1.1\r\nHost: example.com\r\nContent-Length: 00012",
    b"POST /items HTTP/1.1\r\nHost: example.com\r\nContent-Length: 01\r\nContent-Length: 1",
    b"GET / HTTP/1.1\r\nHost: [::1]:8000",
    b"GET / HTTP/1.1\r\nHost: [V1.fe]:80",
    b"GET / HTTP/1.1\r\nHost: example.com\r\nCookie: a=1\r\nCookie: b=2",
    b"GET / HTTP/1.1\r\nHost: example.com\r\nX-Test: \xff",
    b"BROKEN",
    b"GET  / HTTP/1.1\r\nHost: example.com",
    b"GET relative HTTP/1.1\r\nHost: example.com",
    b"GET / HTTP/2.0\r\nHost: example.com",
    b"G(ET / HTTP/1.1\r\nHost: example.com",
    b"GET / HTTP/1.1",
    b"GET / HTTP/1.1\r\nHost: one\r\nHost: two",
    b"GET / HTTP/1.1\r\nHost: bad host",
    b"GET / HTTP/1.1\r\nHost: [::1",
    b"GET / HTTP/1.1\r\nHost: user@example.com",
    b"GET / HTTP/1.1\r\nHost: example.com:99999",
    b"GET / HTTP/1.1\r\n folded: value\r\nHost: example.com",
    b"GET / HTTP/1.1\r\nBad Header: value\r\nHost: example.com",
    b"GET / HTTP/1.1\r\nHost: ex\x00ample.com",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nContent-Length: nope",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nContent-Length: -1",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nContent-Length: 1, 1",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nContent-Length: 1\r\nContent-Length: 2",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked\r\nContent-Length: 999999999999999999999999",
    b"POST / HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked\r\nContent-Length: 1\r\nContent-Length: 2",
    b"GET / HTTP/1.0\r\nConnection: keep-alive, close",
    b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: keep-alive\r\nConnection: close",
    b"GET / HTTP/1.1\nHost: example.com",
    b"GET / HTTP/1.1\rHost: example.com",
]


@pytest.mark.parametrize("head", CORPUS)
def test_direct_differential_corpus(head: bytes) -> None:
    assert_parity(head)


@pytest.mark.parametrize(
    ("head", "limits"),
    [
        (b"GET / HTTP/1.1\r\nHost: x", (27, 64, 10, 100)),
        (b"GET / HTTP/1.1\r\nHost: x", (26, 64, 10, 100)),
        (b"GET / HTTP/1.1\r\nHost: x", (100, 27, 10, 100)),
        (b"GET / HTTP/1.1\r\nHost: x", (100, 26, 10, 100)),
        (b"GET / HTTP/1.1\r\nHost: x\r\nX: 1", (100, 100, 2, 100)),
        (b"GET / HTTP/1.1\r\nHost: x\r\nX: 1", (100, 100, 1, 100)),
        (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 100", (100, 100, 10, 100)),
        (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 101", (100, 100, 10, 100)),
        (b"POST / HTTP/1.1\r\nContent-Length: 101", (100, 100, 10, 100)),
    ],
)
def test_limit_boundaries(
    head: bytes,
    limits: tuple[int, int, int, int],
) -> None:
    assert_parity(head, limits)


def test_seeded_byte_mutations_never_diverge_or_panic() -> None:
    randomizer = random.Random(20260828)
    seeds = [
        bytearray(b"GET /items/42 HTTP/1.1\r\nHost: example.com\r\nConnection: keep-alive"),
        bytearray(
            b"POST /items HTTP/1.1\r\nHost: example.com\r\nContent-Length: 32\r\nX-Test: value"
        ),
    ]
    for _ in range(50_000):
        candidate = bytearray(randomizer.choice(seeds))
        for _ in range(randomizer.randint(1, 4)):
            operation = randomizer.randrange(3)
            if operation == 0 and candidate:
                candidate[randomizer.randrange(len(candidate))] = randomizer.randrange(256)
            elif operation == 1 and candidate:
                del candidate[randomizer.randrange(len(candidate))]
            else:
                candidate.insert(
                    randomizer.randrange(len(candidate) + 1), randomizer.randrange(256)
                )
        assert_parity(bytes(candidate))


def test_concurrent_calls_are_stateless_and_deterministic() -> None:
    head = b"POST /items HTTP/1.1\r\nHost: example.com\r\nContent-Length: 32"
    expected = native_parse_head(head)

    def parse_many(_worker: int) -> None:
        for _ in range(2_000):
            assert native_parse_head(head) == expected

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(parse_many, range(16)))
