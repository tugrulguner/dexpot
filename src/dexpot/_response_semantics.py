"""Semantic primitives shared by checked-response preparation engines."""

from __future__ import annotations

import math
import types
import typing
from dataclasses import is_dataclass
from typing import Annotated, Any, get_args, get_origin

import msgspec


def reject_nonfinite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite floats are not supported in checked responses")
    if isinstance(value, dict):
        for key, item in value.items():
            reject_nonfinite(key)
            reject_nonfinite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_nonfinite(item)


def check_length(value: Any, info: Any) -> None:
    if info.min_length is not None and len(value) < info.min_length:
        raise ValueError("response collection is too short")
    if info.max_length is not None and len(value) > info.max_length:
        raise ValueError("response collection is too long")


def omitted(value: Any, default: Any, factory: Any, enabled: bool, *, wire: bool = False) -> bool:
    if not enabled:
        return False
    if default is not msgspec.NODEFAULT and value is default:
        return True
    expected = list if wire and factory is set else factory
    return factory in (list, dict, set) and type(value) is expected and not value


def substitute(annotation: Any, bindings: dict[Any, Any]) -> Any:
    """Resolve generic record fields once, retaining Annotated metadata."""
    if isinstance(annotation, typing.TypeVar):
        return bindings.get(annotation, Any)
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    args = tuple(substitute(arg, bindings) for arg in get_args(annotation))
    if origin is Annotated:
        return Annotated[args]
    if origin in (typing.Union, types.UnionType):
        return typing.Union[args]  # noqa: UP007 -- reconstruct a dynamic union at registration
    if hasattr(annotation, "copy_with"):
        return annotation.copy_with(args)
    return origin[args]


def type_info(annotation: Any) -> Any:
    """JSON-schema documentation metadata does not change runtime preparation."""
    info = msgspec.inspect.type_info(annotation)
    while isinstance(info, msgspec.inspect.Metadata):
        info = info.type
    return info


def is_record(value: Any) -> bool:
    return not isinstance(value, type) and (
        is_dataclass(value) or hasattr(type(value), "__attrs_attrs__")
    )
