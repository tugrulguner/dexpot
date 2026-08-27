"""Bounded HTTP/1.x request parsing for dexpot's owned socket runtime."""

from __future__ import annotations

import math
import re
import socket
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes

_TOKEN = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HEX = frozenset(b"0123456789abcdefABCDEF")


@dataclass(frozen=True, slots=True)
class HttpLimits:
    """Resource limits enforced while reading one HTTP request.

    Defaults are conservative enough for ordinary JSON APIs while preventing
    unbounded request-head, header, body, and idle-read accumulation.
    """

    request_line_bytes: int = 8 * 1024
    header_bytes: int = 64 * 1024
    header_count: int = 100
    body_bytes: int = 16 * 1024 * 1024
    idle_read_seconds: float = 5.0

    def __post_init__(self) -> None:
        integer_values = {
            "request_line_bytes": self.request_line_bytes,
            "header_bytes": self.header_bytes,
            "header_count": self.header_count,
            "body_bytes": self.body_bytes,
        }
        for name, value in integer_values.items():
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if isinstance(self.idle_read_seconds, bool) or not isinstance(
            self.idle_read_seconds, (int, float)
        ):
            raise TypeError("idle_read_seconds must be a number")
        if not math.isfinite(self.idle_read_seconds):
            raise ValueError("idle_read_seconds must be finite")
        if self.idle_read_seconds <= 0:
            raise ValueError("idle_read_seconds must be positive")
        if self.header_bytes <= self.request_line_bytes:
            raise ValueError("header_bytes must be greater than request_line_bytes")


@dataclass(frozen=True, slots=True)
class ParsedRequest:
    method: str
    path: str
    query: str
    version: str
    headers: dict[str, str]
    body: bytes
    keep_alive: bool


class HTTPParseError(Exception):
    """A public, fail-closed HTTP parsing failure."""

    def __init__(self, status: int, detail: str, version: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.version = version

    def with_version(self, version: str) -> HTTPParseError:
        self.version = version
        return self


class ClientDisconnected(ConnectionError):
    """The peer closed a connection without a complete request to answer."""


def _recv(conn: socket.socket) -> bytes:
    try:
        return conn.recv(65536)
    except TimeoutError as exc:
        raise HTTPParseError(408, "request timeout") from exc


def _validate_request_line(line: bytes, limit: int) -> tuple[str, bytes, str]:
    if len(line) > limit:
        raise HTTPParseError(414, "request target too long")
    parts = line.split(b" ")
    if len(parts) != 3 or any(not part for part in parts):
        raise HTTPParseError(400, "malformed request line")
    method_bytes, target, version_bytes = parts
    if not _TOKEN.fullmatch(method_bytes):
        raise HTTPParseError(400, "invalid method")
    if version_bytes not in (b"HTTP/1.0", b"HTTP/1.1"):
        raise HTTPParseError(505, "HTTP version not supported")
    if (
        not target.startswith(b"/")
        or b"#" in target
        or any(byte < 0x21 or byte > 0x7E for byte in target)
    ):
        raise HTTPParseError(400, "invalid request target")
    return (
        method_bytes.decode("ascii"),
        target,
        version_bytes.decode("ascii"),
    )


def _decode_path(target: bytes) -> tuple[str, str]:
    raw_path, separator, raw_query = target.partition(b"?")
    index = 0
    while True:
        index = target.find(b"%", index)
        if index < 0:
            break
        if (
            index + 2 >= len(target)
            or target[index + 1] not in _HEX
            or target[index + 2] not in _HEX
        ):
            raise HTTPParseError(400, "invalid request target escape")
        index += 3
    try:
        path = unquote_to_bytes(raw_path).decode("utf-8")
        query = raw_query.decode("ascii") if separator else ""
    except UnicodeDecodeError as exc:
        raise HTTPParseError(400, "invalid request target encoding") from exc
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        raise HTTPParseError(400, "invalid request target")
    return path, query


def _parse_headers(lines: list[bytes], limit: int) -> tuple[dict[str, str], int]:
    if len(lines) > limit:
        raise HTTPParseError(431, "too many headers")

    headers: dict[str, str] = {}
    lengths: list[int] = []
    transfer_encoding = False
    for line in lines:
        if not line or line[:1] in (b" ", b"\t") or b":" not in line:
            raise HTTPParseError(400, "malformed header")
        raw_name, raw_value = line.split(b":", 1)
        if not _TOKEN.fullmatch(raw_name):
            raise HTTPParseError(400, "malformed header name")
        name = raw_name.decode("ascii").lower()
        value_bytes = raw_value.strip(b" \t")
        if any((byte < 0x20 and byte != 0x09) or byte == 0x7F for byte in value_bytes):
            raise HTTPParseError(400, "malformed header value")
        value = value_bytes.decode("latin-1")
        if name == "host" and name in headers:
            raise HTTPParseError(400, "multiple host headers")
        if name == "content-length":
            if not value_bytes or not value_bytes.isdigit():
                raise HTTPParseError(400, "invalid content-length")
            try:
                lengths.append(int(value_bytes))
            except ValueError as exc:
                raise HTTPParseError(400, "invalid content-length") from exc
        elif name == "transfer-encoding":
            transfer_encoding = True
        if name in headers and name not in ("content-length", "cookie"):
            headers[name] = f"{headers[name]}, {value}"
        elif name == "cookie" and name in headers:
            headers[name] = f"{headers[name]}; {value}"
        else:
            headers[name] = value

    if transfer_encoding:
        raise HTTPParseError(400, "transfer-encoding is not supported")
    if lengths and any(length != lengths[0] for length in lengths[1:]):
        raise HTTPParseError(400, "conflicting content-length headers")
    return headers, lengths[0] if lengths else 0


def read_request(
    conn: socket.socket,
    buf: bytes,
    limits: HttpLimits,
) -> tuple[ParsedRequest, bytes]:
    """Read and parse one bounded request, preserving pipelined bytes."""

    delimiter = b"\r\n\r\n"
    while delimiter not in buf:
        first_line_end = buf.find(b"\r\n")
        if first_line_end >= 0:
            if first_line_end > limits.request_line_bytes:
                raise HTTPParseError(414, "request target too long")
        elif len(buf) > limits.request_line_bytes:
            raise HTTPParseError(414, "request target too long")
        if len(buf) > limits.header_bytes:
            raise HTTPParseError(431, "request headers too large")
        chunk = _recv(conn)
        if not chunk:
            if not buf:
                raise ClientDisconnected()
            raise HTTPParseError(400, "incomplete request head")
        buf += chunk

    head, _, rest = buf.partition(delimiter)
    if len(head) > limits.header_bytes:
        raise HTTPParseError(431, "request headers too large")
    lines = head.split(b"\r\n")
    method, target, version = _validate_request_line(lines[0], limits.request_line_bytes)
    try:
        headers, content_length = _parse_headers(lines[1:], limits.header_count)
    except HTTPParseError as exc:
        raise exc.with_version(version) from None
    if version == "HTTP/1.1" and not headers.get("host", "").strip():
        raise HTTPParseError(400, "missing host header", version)
    if content_length > limits.body_bytes:
        raise HTTPParseError(413, "request body too large", version)

    while len(rest) < content_length:
        try:
            chunk = _recv(conn)
        except HTTPParseError as exc:
            raise exc.with_version(version) from None
        if not chunk:
            raise HTTPParseError(400, "incomplete request body", version)
        rest += chunk
    body, remaining = rest[:content_length], rest[content_length:]
    try:
        path, query = _decode_path(target)
    except HTTPParseError as exc:
        raise exc.with_version(version) from None

    connection_tokens = {
        token.strip().lower() for token in headers.get("connection", "").split(",") if token.strip()
    }
    keep_alive = "close" not in connection_tokens and (
        version == "HTTP/1.1" or "keep-alive" in connection_tokens
    )
    return (
        ParsedRequest(
            method=method,
            path=path,
            query=query,
            version=version,
            headers=headers,
            body=body,
            keep_alive=keep_alive,
        ),
        remaining,
    )
