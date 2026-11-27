"""Explicit scalar HTTP input descriptors and request-local binding."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, cast, get_args, get_origin
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
    repeated: bool = field(init=False)
    scalar_type: type = field(init=False, repr=False)

    def __post_init__(self) -> None:
        repeated = self.source == "query" and get_origin(self.annotation) is list
        args = get_args(self.annotation) if repeated else (self.annotation,)
        if len(args) != 1 or not any(args[0] is typ for typ in (str, int, float, bool)):
            raise TypeError(
                "input types must be str, int, float or bool; queries also accept lists of these types"
            )
        scalar = args[0]
        if self.default is not _MISSING:
            if repeated and type(self.default) is not list:
                raise TypeError("repeated query defaults must be lists")
            values = tuple(self.default) if repeated else (self.default,)
            if any(
                type(item) is not scalar
                or (scalar is float and not math.isfinite(cast(float, item)))
                for item in values
            ):
                raise TypeError("input defaults must have the exact finite scalar type")
            if repeated:
                object.__setattr__(self, "default", values)
        object.__setattr__(self, "repeated", repeated)
        object.__setattr__(self, "scalar_type", scalar)
        converter = (
            str
            if scalar is str
            else _as_int
            if scalar is int
            else _as_float
            if scalar is float
            else _as_bool
        )
        object.__setattr__(self, "convert", converter)


class InputError(ValueError):
    """A sanitized, client-facing source binding error."""


def _decode_query_component(text: str) -> str:
    return unquote_to_bytes(text.replace("+", " ")).decode("utf-8")


def decode_query_pairs(query: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    try:
        for segment in query.split("&"):
            if segment:
                name, _, value = segment.partition("=")
                pairs.append((_decode_query_component(name), _decode_query_component(value)))
    except UnicodeDecodeError:
        raise ValueError("invalid query encoding") from None
    return tuple(pairs)


def _query_pairs(query: str) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    try:
        for segment in query.split("&"):
            if segment:
                raw_name, _, value = segment.partition("=")
                name = _decode_query_component(raw_name)
                pairs.setdefault(name, []).append(value)
    except UnicodeDecodeError:
        raise InputError("invalid query encoding") from None
    return pairs


def iter_cookie_pairs(raw: str) -> Iterator[tuple[str, str]]:
    if raw:
        for segment in raw.split(";"):
            name, separator, value = segment.strip(" \t").partition("=")
            if not separator or not _TOKEN.fullmatch(name):
                raise InputError("invalid cookie header")
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if not _COOKIE.fullmatch(value):
                raise InputError("invalid cookie header")
            yield name, value


def _cookie_pairs(raw: str) -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    for name, value in iter_cookie_pairs(raw):
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


def _convert_input(binding: InputBinding, text: str) -> Any:
    if binding.source == "query":
        try:
            text = _decode_query_component(text)
        except UnicodeDecodeError:
            raise InputError(f"query parameter '{binding.name}': encoding") from None
    try:
        return binding.convert(text)
    except (ValueError, OverflowError):
        raise InputError(f"{binding.source} parameter '{binding.name}': invalid") from None


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
            if binding.repeated:
                if values:
                    result.append([_convert_input(binding, item) for item in values])
                elif binding.default is _MISSING:
                    raise InputError(f"query parameter '{binding.name}': missing")
                else:
                    result.append(list(binding.default))
                continue
            if len(values) > 1:
                raise InputError(f"{binding.source} parameter '{binding.name}': repeated")
            value = values[0] if values else _MISSING
        if value is _MISSING:
            if binding.default is _MISSING:
                raise InputError(f"{binding.source} parameter '{binding.name}': missing")
            result.append(binding.default)
            continue
        result.append(_convert_input(binding, cast(str, value)))
    return tuple(result)
