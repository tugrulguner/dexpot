"""Typed request context passed directly to annotated handlers."""

from __future__ import annotations

from typing import Any

import msgspec

from ._inputs import decode_query_pairs, iter_cookie_pairs


class Request(msgspec.Struct, frozen=True, gc=True):
    """Parsed request metadata and route-validated body state."""

    method: str
    path: str
    params: dict[str, str]
    query: str
    headers: dict[str, str]
    raw_body: bytes = b""
    body: Any = None
    peer: tuple[str, int] | None = None

    def query_pairs(self) -> tuple[tuple[str, str], ...]:
        """Decode ordered query pairs on demand; raise ValueError for invalid UTF-8."""
        return decode_query_pairs(self.query)

    def cookie_pairs(self) -> tuple[tuple[str, str], ...]:
        """Parse ordered Cookie pairs on demand; raise ValueError for malformed syntax."""
        return tuple(iter_cookie_pairs(self.headers.get("cookie", "")))
