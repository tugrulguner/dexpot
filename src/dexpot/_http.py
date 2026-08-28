"""Bounded HTTP/1.x request parsing for dexpot's owned socket runtime."""

from __future__ import annotations

import importlib
import ipaddress
import math
import os
import re
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes

_TOKEN = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HEX = frozenset(b"0123456789abcdefABCDEF")
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_SUB_DELIMS = frozenset(b"!$&'()*+,;=")
_PCHAR = _UNRESERVED | _SUB_DELIMS | frozenset(b":@")
_QUERY_CHAR = _PCHAR | frozenset(b"/?")
_REG_NAME = re.compile(rb"^(?:[A-Za-z0-9._~-]|[!$&'()*+,;=]|%[0-9A-Fa-f]{2})+$")
_IPV_FUTURE = re.compile(rb"^[vV][0-9A-Fa-f]+\.[A-Za-z0-9._~!$&'()*+,;=:-]+$")


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
    head_read_seconds: float = 10.0
    body_read_seconds: float = 30.0

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
        timeout_values = {
            "idle_read_seconds": self.idle_read_seconds,
            "head_read_seconds": self.head_read_seconds,
            "body_read_seconds": self.body_read_seconds,
        }
        for name, value in timeout_values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
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


def _recv(
    conn: socket.socket,
    *,
    deadline: float,
    idle_seconds: float,
    version: str | None = None,
) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HTTPParseError(408, "request timeout", version)
    conn.settimeout(min(idle_seconds, remaining))
    try:
        return conn.recv(65536)
    except TimeoutError as exc:
        raise HTTPParseError(408, "request timeout", version) from exc


def _validate_request_line(line: bytes, limit: int) -> tuple[str, bytes, str]:
    if len(line) > limit:
        raise HTTPParseError(414, "request target too long")
    parts = line.split(b" ")
    if len(parts) != 3 or any(not part for part in parts):
        raise HTTPParseError(400, "malformed request line")
    method_bytes, target, version_bytes = parts
    if version_bytes not in (b"HTTP/1.0", b"HTTP/1.1"):
        raise HTTPParseError(505, "HTTP version not supported")
    version = version_bytes.decode("ascii")
    if not _TOKEN.fullmatch(method_bytes):
        raise HTTPParseError(400, "invalid method", version)
    if not target.startswith(b"/"):
        raise HTTPParseError(400, "invalid request target", version)
    return method_bytes.decode("ascii"), target, version


def _validate_target_component(raw: bytes, allowed: frozenset[int]) -> None:
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x25:  # percent escape
            if index + 2 >= len(raw) or raw[index + 1] not in _HEX or raw[index + 2] not in _HEX:
                raise HTTPParseError(400, "invalid request target escape")
            index += 3
            continue
        if byte not in allowed:
            raise HTTPParseError(400, "invalid request target")
        index += 1


def _decode_path(target: bytes) -> tuple[str, str]:
    if b"#" in target:
        raise HTTPParseError(400, "invalid request target")
    raw_path, separator, raw_query = target.partition(b"?")
    _validate_target_component(raw_path, _PCHAR | frozenset(b"/"))
    if separator:
        _validate_target_component(raw_query, _QUERY_CHAR)
    try:
        path = unquote_to_bytes(raw_path).decode("utf-8")
        query = raw_query.decode("ascii") if separator else ""
    except UnicodeDecodeError as exc:
        raise HTTPParseError(400, "invalid request target encoding") from exc
    # Percent escapes are syntax-checked above, but their decoded octets must
    # not reintroduce controls into routing, handlers, or diagnostic logs.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        raise HTTPParseError(400, "invalid request target")
    return path, query


def _validate_port(raw: bytes) -> None:
    if not raw or not raw.isdigit():
        raise HTTPParseError(400, "invalid host header")
    # Avoid interpreter-dependent huge-int parsing and reject unusable ports.
    if len(raw) > 5 or int(raw) > 65535:
        raise HTTPParseError(400, "invalid host header")


def _validate_host(raw: bytes) -> None:
    if not raw or b"," in raw or b"@" in raw or any(byte > 0x7F for byte in raw):
        raise HTTPParseError(400, "invalid host header")
    if raw.startswith(b"["):
        close = raw.find(b"]")
        if close <= 1:
            raise HTTPParseError(400, "invalid host header")
        literal = raw[1:close]
        suffix = raw[close + 1 :]
        if suffix:
            if not suffix.startswith(b":"):
                raise HTTPParseError(400, "invalid host header")
            _validate_port(suffix[1:])
        try:
            if literal[:1].lower() == b"v":
                if not _IPV_FUTURE.fullmatch(literal):
                    raise ValueError
            else:
                ipaddress.IPv6Address(literal.decode("ascii"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPParseError(400, "invalid host header") from exc
        return

    if raw.count(b":") > 1:
        raise HTTPParseError(400, "invalid host header")
    host, separator, port = raw.rpartition(b":")
    if separator:
        _validate_port(port)
    else:
        host = raw
    if not host or not _REG_NAME.fullmatch(host):
        raise HTTPParseError(400, "invalid host header")


def _canonical_decimal(raw: bytes) -> bytes:
    if not raw or not raw.isdigit():
        raise HTTPParseError(400, "invalid content-length")
    return raw.lstrip(b"0") or b"0"


def _parse_headers(lines: list[bytes], limit: int, body_limit: int) -> tuple[dict[str, str], int]:
    if len(lines) > limit:
        raise HTTPParseError(431, "too many headers")

    headers: dict[str, str] = {}
    lengths: list[bytes] = []
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
        if name == "host":
            _validate_host(value_bytes)
        if name == "content-length":
            lengths.append(_canonical_decimal(value_bytes))
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
    if not lengths:
        return headers, 0
    length = lengths[0]
    limit_bytes = str(body_limit).encode("ascii")
    if len(length) > len(limit_bytes) or (len(length) == len(limit_bytes) and length > limit_bytes):
        raise HTTPParseError(413, "request body too large")
    return headers, int(length)


HeadResult = tuple[str, bytes, str, dict[str, str], int, bool]
HeadParser = Callable[[bytes, HttpLimits], HeadResult]


def _parse_head_python(head: bytes, limits: HttpLimits) -> HeadResult:
    lines = head.split(b"\r\n")
    method, target, version = _validate_request_line(lines[0], limits.request_line_bytes)
    try:
        headers, content_length = _parse_headers(lines[1:], limits.header_count, limits.body_bytes)
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


def _select_head_parser() -> tuple[str, HeadParser]:
    requested = os.environ.get("DEXPOT_HTTP_PARSER", "auto").lower()
    if requested not in {"python", "native", "auto"}:
        raise ValueError("DEXPOT_HTTP_PARSER must be one of: python, native, auto")
    if requested == "python":
        return "python", _parse_head_python

    try:
        native_package = importlib.import_module("dexpot_native")
    except ModuleNotFoundError as exc:
        if exc.name != "dexpot_native":
            raise
        if requested == "native":
            raise RuntimeError(
                "DEXPOT_HTTP_PARSER=native was requested, but dexpot-native is not installed"
            ) from exc
        return "python", _parse_head_python

    if getattr(native_package, "PARSER_API_VERSION", None) != 1:
        raise RuntimeError("incompatible dexpot-native parser API; dexpot requires API version 1")
    native_parser = importlib.import_module("dexpot_native._parser")

    def parse_native(head: bytes, limits: HttpLimits) -> HeadResult:
        if any(
            value > sys.maxsize
            for value in (
                limits.request_line_bytes,
                limits.header_bytes,
                limits.header_count,
                limits.body_bytes,
            )
        ):
            return _parse_head_python(head, limits)
        try:
            return native_parser.parse_head(
                head,
                limits.request_line_bytes,
                limits.header_bytes,
                limits.header_count,
                limits.body_bytes,
            )
        except ValueError as exc:
            if len(exc.args) != 3:
                raise
            status, detail, version = exc.args
            raise HTTPParseError(status, detail, version) from None

    return "native", parse_native


PARSER_BACKEND, _parse_head = _select_head_parser()


def read_request(
    conn: socket.socket,
    buf: bytes,
    limits: HttpLimits,
) -> tuple[ParsedRequest, bytes]:
    """Read and parse one bounded request, preserving pipelined bytes."""

    delimiter = b"\r\n\r\n"
    head_deadline = time.monotonic() + limits.head_read_seconds
    head_buffer = bytearray(buf)
    while True:
        delimiter_index = head_buffer.find(delimiter)
        if delimiter_index >= 0:
            break
        first_line_end = head_buffer.find(b"\r\n")
        if first_line_end >= 0:
            if first_line_end > limits.request_line_bytes:
                raise HTTPParseError(414, "request target too long")
        elif len(head_buffer) > limits.request_line_bytes:
            raise HTTPParseError(414, "request target too long")
        if len(head_buffer) > limits.header_bytes:
            raise HTTPParseError(431, "request headers too large")
        chunk = _recv(
            conn,
            deadline=head_deadline,
            idle_seconds=limits.idle_read_seconds,
        )
        if not chunk:
            if not head_buffer:
                raise ClientDisconnected()
            raise HTTPParseError(400, "incomplete request head")
        head_buffer.extend(chunk)

    head = bytes(head_buffer[:delimiter_index])
    rest = bytes(head_buffer[delimiter_index + len(delimiter) :])
    if len(head) > limits.header_bytes:
        raise HTTPParseError(431, "request headers too large")
    method, target, version, headers, content_length, keep_alive = _parse_head(head, limits)

    if len(rest) >= content_length:
        body = rest[:content_length]
        remaining = rest[content_length:]
    else:
        body_deadline = time.monotonic() + limits.body_read_seconds
        body_buffer = bytearray(rest)
        remaining = b""
        while len(body_buffer) < content_length:
            try:
                chunk = _recv(
                    conn,
                    deadline=body_deadline,
                    idle_seconds=limits.idle_read_seconds,
                    version=version,
                )
            except HTTPParseError as exc:
                raise exc.with_version(version) from None
            if not chunk:
                raise HTTPParseError(400, "incomplete request body", version)
            needed = content_length - len(body_buffer)
            body_buffer.extend(chunk[:needed])
            if len(chunk) > needed:
                remaining = chunk[needed:]
                break
        body = bytes(body_buffer)

    try:
        path, query = _decode_path(target)
    except HTTPParseError as exc:
        raise exc.with_version(version) from None

    # `_recv` tightens the socket timeout to the remaining absolute deadline.
    # Restore the normal idle timeout before response writes or the next request.
    conn.settimeout(limits.idle_read_seconds)
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
