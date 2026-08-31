"""Immutable application and routing plans compiled before serving traffic."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import msgspec

_json_encode = msgspec.json.encode

_type_hints_cache: dict[Any, dict[str, Any]] = {}


class _ApplicationCompilationDuringRegistration(RuntimeError):
    """Keep registration-control failures visible during annotation evaluation."""


def _type_hints(fn: Any) -> dict[str, Any]:
    hints = _type_hints_cache.get(fn)
    if hints is None:
        raw = {
            name: parameter.annotation
            for name, parameter in inspect.signature(fn).parameters.items()
        }
        resolved: dict[str, Any] = {}
        globalns = getattr(fn, "__globals__", {})
        closure = fn.__closure__ or ()
        cell_names = fn.__code__.co_freevars
        cells = dict(zip(cell_names, (cell.cell_contents for cell in closure), strict=True))
        for name, annotation in raw.items():
            if isinstance(annotation, str):
                try:
                    annotation = eval(annotation, dict(typing.__dict__), {**globalns, **cells})
                except _ApplicationCompilationDuringRegistration:
                    raise
                except Exception:
                    pass
            resolved[name] = annotation
        hints = resolved
        _type_hints_cache[fn] = hints
    return hints


@dataclass(frozen=True, slots=True, init=False)
class EndpointPlan:
    """Compiled immutable handler binding and codec plan."""

    bind: Any
    body_decoder: Any
    body_type: Any
    handler: Callable[..., Any]
    int_captures: tuple[tuple[int, str], ...]
    method: str
    path: str
    path_names: tuple[str, ...]
    resp_encoder: Any
    resp_type: Any
    summary: str

    def __init__(
        self,
        method: str,
        path: str,
        handler: Callable[..., Any],
        body_type: Any,
        resp_type: Any,
        summary: str,
        path_names: list[str],
    ) -> None:
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "handler", handler)
        object.__setattr__(self, "body_type", body_type)
        object.__setattr__(self, "resp_type", resp_type)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "path_names", tuple(path_names))
        object.__setattr__(
            self,
            "body_decoder",
            msgspec.json.Decoder(body_type) if body_type is not None else None,
        )
        object.__setattr__(
            self,
            "resp_encoder",
            msgspec.json.Encoder() if resp_type is not None else None,
        )

        hints = _type_hints(handler)
        signature = inspect.signature(handler)
        captures_by_name = {name: index for index, name in enumerate(path_names)}
        sources: list[tuple[Any, str, str, Any]] = []
        int_captures: list[tuple[int, str]] = []
        used_captures: set[int] = set()
        body_param_seen = False

        for name, parameter in signature.parameters.items():
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"handler parameter '{name}' uses unsupported "
                    f"{parameter.kind.description}; *args/**kwargs cannot be compiled"
                )

            annotation = hints.get(name)
            if name in captures_by_name:
                index = captures_by_name[name]
                if annotation is int:
                    int_captures.append((index, name))
                sources.append((parameter.kind, name, "capture", index))
                used_captures.add(index)
            elif body_type is not None and not body_param_seen:
                body_param_seen = True
                sources.append((parameter.kind, name, "body", None))
            elif parameter.default is not inspect.Parameter.empty:
                sources.append((parameter.kind, name, "default", parameter.default))
            else:
                raise TypeError(
                    f"handler parameter '{name}' on route "
                    "cannot be bound: no matching path segment, body, or default"
                )

        object.__setattr__(self, "int_captures", tuple(int_captures))
        positional_sources = [
            (source, payload)
            for kind, _name, source, payload in sources
            if kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        keyword_sources = [
            (name, source, payload)
            for kind, name, source, payload in sources
            if kind is inspect.Parameter.KEYWORD_ONLY
        ]

        def resolve(source: str, payload: Any, captures: list[Any], body: Any) -> Any:
            if source == "capture":
                return captures[payload]
            if source == "body":
                return body
            return payload

        def bind(captures: list[Any], body: Any) -> tuple[list[Any], dict[str, Any] | None]:
            args = [
                resolve(source, payload, captures, body) for source, payload in positional_sources
            ]
            kwargs = (
                {
                    name: resolve(source, payload, captures, body)
                    for name, source, payload in keyword_sources
                }
                if keyword_sources
                else None
            )
            return args, kwargs

        object.__setattr__(self, "bind", bind)
        unconsumed = [
            path_names[index] for index in range(len(path_names)) if index not in used_captures
        ]
        if unconsumed:
            raise TypeError(f"path parameter(s) {unconsumed} are not accepted by the handler")

    def encode(self, result: Any) -> bytes:
        """Encode a successful result using the endpoint response contract."""
        if self.resp_encoder is not None and type(result) is self.resp_type:
            return self.resp_encoder.encode(result)
        return _json_encode(result)


@dataclass(frozen=True, slots=True)
class ParametricRoute:
    method: str
    segments: tuple[str | None, ...]
    endpoint: EndpointPlan


@dataclass(frozen=True, slots=True)
class RouterPlan:
    """Immutable route lookup data compiled from application declarations."""

    literal: Mapping[tuple[str, str], EndpointPlan]
    parametric_by_length: Mapping[int, tuple[ParametricRoute, ...]]

    @classmethod
    def compile(
        cls,
        literal: Mapping[tuple[str, str], EndpointPlan],
        parametric: Sequence[tuple[str, Sequence[str], EndpointPlan]],
    ) -> RouterPlan:
        by_length: dict[int, list[ParametricRoute]] = {}
        for method, segments, endpoint in parametric:
            compiled_segments = tuple(
                None if segment.startswith("{") and segment.endswith("}") else segment
                for segment in segments
            )
            route = ParametricRoute(method, compiled_segments, endpoint)
            by_length.setdefault(len(route.segments), []).append(route)
        return cls(
            literal=MappingProxyType(dict(literal)),
            parametric_by_length=MappingProxyType(
                {length: tuple(routes) for length, routes in by_length.items()}
            ),
        )

    def match(
        self, method: str, path: str
    ) -> tuple[EndpointPlan | None, list[Any] | None, tuple[str, ...]]:
        hit = self.literal.get((method, path))
        if hit is not None:
            return hit, [], ()
        return self.match_after_literal_miss(method, path)

    def match_after_literal_miss(
        self, method: str, path: str
    ) -> tuple[EndpointPlan | None, list[Any] | None, tuple[str, ...]]:
        """Resolve methods and parameterized routes after an exact miss."""
        allowed = {
            registered_method
            for registered_method, registered_path in self.literal
            if registered_path == path
        }
        segments = [] if path == "/" else path[1:].split("/")
        for route in self.parametric_by_length.get(len(segments), ()):
            captures: list[Any] = []
            for expected, actual in zip(route.segments, segments, strict=True):
                if expected is None:
                    captures.append(actual)
                elif expected != actual:
                    break
            else:
                if route.method == method:
                    return route.endpoint, captures, ()
                allowed.add(route.method)
        return None, None, tuple(sorted(allowed))


@dataclass(frozen=True, slots=True)
class ApplicationPlan:
    """The immutable request-execution plan for one compiled application."""

    endpoints: tuple[EndpointPlan, ...]
    router: RouterPlan
