"""Explicit scalar HTTP input descriptors and request-local binding."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import unquote_to_bytes

_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_INT = re.compile(r"[+-]?[0-9]+")
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_COOKIE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*")
_MISSING = object()


def _name(source: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("input names must be nonempty strings")
    if source == "query":
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise TypeError("invalid query input name") from None
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise TypeError("invalid query input name")
    elif not value.isascii() or not _TOKEN.fullmatch(value):
        raise TypeError("invalid header or cookie input name")
    return value.lower() if source == "header" else value


@dataclass(frozen=True, slots=True)
class Query:
    """Declare an explicitly named query input."""

    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name("query", self.name))


@dataclass(frozen=True, slots=True)
class Header:
    """Declare an explicitly named normalized header input."""

    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name("header", self.name))


@dataclass(frozen=True, slots=True)
class Cookie:
    """Declare an explicitly named cookie input."""

    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name("cookie", self.name))


def get_marker(value: Any) -> tuple[str, str] | None:
    for marker, source in ((Query, "query"), (Header, "header"), (Cookie, "cookie")):
        if type(value) is marker:
            return source, value.name
    return None


@dataclass(frozen=True, slots=True)
class InputBinding:
    source: str
    name: str
    annotation: Any
    default: Any = _MISSING
    convert: Callable[[str], Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not any(self.annotation is typ for typ in (str, int, float, bool)):
            raise TypeError("input types must be str, int, float or bool")
        if self.default is not _MISSING and (
            type(self.default) is not self.annotation
            or (self.annotation is float and not math.isfinite(self.default))
        ):
            raise TypeError("input defaults must have the exact finite scalar type")
        converter = (
            str
            if self.annotation is str
            else _as_int
            if self.annotation is int
            else _as_float
            if self.annotation is float
            else _as_bool
        )
        object.__setattr__(self, "convert", converter)


class InputError(ValueError):
    """A sanitized, client-facing source binding error."""


def _query_pairs(query: str) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    try:
        for segment in query.split("&"):
            if segment:
                raw_name, _, value = segment.partition("=")
                name = unquote_to_bytes(raw_name.replace("+", " ")).decode("utf-8")
                pairs.setdefault(name, []).append(value)
    except UnicodeDecodeError:
        raise InputError("invalid query encoding") from None
    return pairs


def _cookie_pairs(raw: str) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    if raw:
        for segment in raw.split(";"):
            name, separator, value = segment.strip(" \t").partition("=")
            if not separator or not _TOKEN.fullmatch(name):
                raise InputError("invalid cookie header")
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if not _COOKIE.fullmatch(value):
                raise InputError("invalid cookie header")
            pairs.setdefault(name, []).append(value)
    return pairs


def _as_int(value: str) -> int:
    if _INT.fullmatch(value):
        return int(value)
    raise ValueError("invalid scalar")


def _as_float(value: str) -> float:
    if _FLOAT.fullmatch(value):
        result = float(value)
        if math.isfinite(result):
            return result
    raise ValueError("invalid scalar")


def _as_bool(value: str) -> bool:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ValueError("invalid scalar")


def bind_inputs(
    bindings: tuple[InputBinding, ...], query: str, headers: Mapping[str, str]
) -> tuple[Any, ...]:
    query_pairs: dict[str, list[str]] | None = None
    cookie_pairs: dict[str, list[str]] | None = None
    result: list[Any] = []
    for binding in bindings:
        if binding.source == "header":
            value = headers.get(binding.name, _MISSING)
        else:
            if binding.source == "query":
                if query_pairs is None:
                    query_pairs = _query_pairs(query)
                values = query_pairs.get(binding.name) or ()
            else:
                if cookie_pairs is None:
                    cookie_pairs = _cookie_pairs(headers.get("cookie", ""))
                values = cookie_pairs.get(binding.name) or ()
            if len(values) > 1:
                raise InputError(f"{binding.source} parameter '{binding.name}': repeated")
            value = values[0] if values else _MISSING
        if value is _MISSING:
            if binding.default is _MISSING:
                raise InputError(f"{binding.source} parameter '{binding.name}': missing")
            result.append(binding.default)
            continue
        text = cast(str, value)
        if binding.source == "query":
            try:
                text = unquote_to_bytes(text.replace("+", " ")).decode("utf-8")
            except UnicodeDecodeError:
                raise InputError(f"query parameter '{binding.name}': encoding") from None
        try:
            result.append(binding.convert(text))
        except (ValueError, OverflowError):
            raise InputError(f"{binding.source} parameter '{binding.name}': invalid") from None
    return tuple(result)
