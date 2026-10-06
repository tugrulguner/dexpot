"""Explicit, immutable application response envelopes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

Headers = Mapping[str, str] | Iterable[tuple[str, str]]
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_OWNED = frozenset(
    {
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "trailer",
        "te",
        "server",
        "content-type",
        "proxy-connection",
    }
)


def _header_value(value: str) -> bytes:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("unsafe response header value")
    return value.encode("latin-1")


def _snapshot_headers(headers: Headers) -> tuple[tuple[str, str], ...]:
    pairs = headers.items() if isinstance(headers, Mapping) else headers
    snapshot = []
    size = 0
    for name, value in pairs:
        if not isinstance(name, str) or not _TOKEN.fullmatch(name) or name.lower() in _OWNED:
            raise ValueError("invalid or server-owned response header")
        size += len(name) + len(_header_value(value)) + 4
        if len(snapshot) >= 64 or size > 16384:
            raise ValueError("response headers exceed limits")
        snapshot.append((name, value))
    return tuple(snapshot)


@dataclass(frozen=True, slots=True, init=False)
class Response:
    """JSON body, final status, and copied headers (including duplicate pairs)."""

    body: Any
    status: int
    headers: tuple[tuple[str, str], ...]

    def __init__(self, body: Any = None, status: int = 200, headers: Headers = ()) -> None:
        if type(status) is not int or not 200 <= status <= 599:
            raise ValueError("response status must be an integer from 200 to 599")
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "headers", _snapshot_headers(headers))


@dataclass(frozen=True, slots=True, init=False)
class RawResponse(Response):
    """Immutable bytes with an explicit media type; requires response=None."""

    body: bytes
    content_type: str

    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: Headers = (),
        content_type: str = "application/octet-stream",
    ) -> None:
        if type(body) is not bytes:
            raise TypeError("raw response body must be bytes")
        if not _header_value(content_type) or len(content_type) > 256:
            raise ValueError("invalid response content type")
        Response.__init__(self, body, status, headers)
        object.__setattr__(self, "content_type", content_type)
