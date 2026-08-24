"""Typed body/response declaration helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def body(model: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the request body type for a handler (a msgspec Struct)."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__dexpot_body__ = model  # type: ignore[attr-defined]
        return fn

    return deco


def response(model: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the response type for a handler (a msgspec Struct)."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__dexpot_resp__ = model  # type: ignore[attr-defined]
        return fn

    return deco
