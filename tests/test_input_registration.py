"""Fail-fast declaration checks for explicit source bindings."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from enum import Enum
from typing import Annotated, Any, Literal, NewType

import pytest

import dexpot
from dexpot import Cookie, Dex, Header, Query, Request


class Choice(Enum):
    ONE = "one"


def handler_for(annotation: Any, default: Any = ...) -> Any:
    def handler(value):
        return value

    handler.__annotations__ = {"value": annotation}
    handler.__defaults__ = () if default is ... else (default,)
    return handler


@pytest.mark.parametrize(
    "base", [Any, Choice, Literal["x"], int | None, list[int], Request, NewType("ID", int)]
)
def test_unsupported_marked_types_fail_even_with_a_default(base):
    app = Dex()
    with pytest.raises(TypeError):
        app.get("/value")(handler_for(Annotated[base, Query("value")], None))
    app.get("/value")(lambda: {"ok": True})


@pytest.mark.parametrize(
    "metadata",
    [
        (Query("value"), "extra"),
        ("extra", Query("value")),
        (Query("value"), Header("x-value")),
    ],
)
def test_extra_source_metadata_is_not_silently_ignored(metadata):
    annotation = Annotated[(int, *metadata)]
    with pytest.raises(TypeError):
        Dex().get("/value")(handler_for(annotation, 0))


@pytest.mark.parametrize(
    "typ,default",
    [
        (int, True),
        (int, "1"),
        (float, 1),
        (float, float("inf")),
        (float, float("nan")),
        (bool, 0),
        (str, None),
        (int, ...),
    ],
)
def test_invalid_typed_defaults_fail_at_registration(typ, default):
    # Ellipsis is a real explicitly supplied default here, not the helper's missing sentinel.
    fn = handler_for(Annotated[typ, Query("value")])
    fn.__defaults__ = (default,)
    with pytest.raises(TypeError):
        Dex().get("/value")(fn)


@pytest.mark.parametrize("marker", [Query, Header, Cookie])
def test_duplicate_normalized_source_aliases_fail(marker):
    def handler(first=0, second=0):
        return first + second

    first = "X-Value" if marker is Header else "value"
    second = "x-value" if marker is Header else "value"
    handler.__annotations__ = {
        "first": Annotated[int, marker(first)],
        "second": Annotated[int, marker(second)],
    }
    with pytest.raises(TypeError):
        Dex().get("/value")(handler)


def test_source_marker_on_a_path_capture_is_rejected_atomically():
    app = Dex()
    fn = handler_for(Annotated[int, Query("value")])
    with pytest.raises(TypeError):
        app.get("/slot/{value}")(fn)
    app.get("/slot/{other}")(lambda other: other)


def test_failed_source_default_does_not_reserve_structural_route():
    app = Dex()

    def invalid(slug, value=None):
        return slug, value

    invalid.__annotations__ = {"slug": str, "value": Annotated[int, Query("value")]}
    with pytest.raises(TypeError):
        app.get("/slot/{slug}")(invalid)
    app.get("/slot/{different}")(lambda different: different)


@pytest.mark.parametrize("value", ["", "\n", "\x7f", "\u0085", "\ud800"])
def test_query_names_reject_controls_or_invalid_utf8(value):
    with pytest.raises(TypeError):
        Query(value)


@pytest.mark.parametrize("marker", [Header, Cookie])
@pytest.mark.parametrize("value", ["", "bad name", "bad:name", "é"])
def test_header_cookie_names_are_ascii_tokens(marker, value):
    with pytest.raises(TypeError):
        marker(value)


@pytest.mark.parametrize("marker", [Query("v"), Header("X-V"), Cookie("v")])
def test_markers_are_immutable(marker):
    with pytest.raises(FrozenInstanceError):
        marker.name = "changed"
    with pytest.raises(FrozenInstanceError):
        delattr(marker, "name")


def test_markers_are_in_the_public_export_list():
    assert {"Query", "Header", "Cookie"} <= set(dexpot.__all__)


def test_non_source_annotation_metadata_keeps_legacy_default_binding():
    Dex().get("/legacy")(handler_for(Annotated[int, "existing app metadata"], 3))
