"""Immutable application and routing plans compiled before serving traffic."""

from __future__ import annotations

import inspect
import typing
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from types import CodeType, FunctionType, MappingProxyType
from typing import Any

import msgspec

_json_encode = msgspec.json.encode

_type_hints_cache: dict[Any, dict[str, Any]] = {}

_Source = tuple[Any, str, str, Any]
_INVOKER_GLOBALS: dict[str, Any] = {}
_INVOKER_CODE_LOCK = Lock()


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


@lru_cache(maxsize=256)
def _invoker_code(parameters: str, arguments: str) -> CodeType:
    source = f"def invoke({parameters}):\n    return _handler({arguments})\n"
    module = compile(source, "<dexpot-endpoint-invoker>", "exec")
    return next(
        constant
        for constant in module.co_consts
        if isinstance(constant, CodeType) and constant.co_name == "invoke"
    )


def _shared_invoker_code(parameters: str, arguments: str) -> CodeType:
    with _INVOKER_CODE_LOCK:
        return _invoker_code(parameters, arguments)


def _compile_invoker(handler: Callable[..., Any], sources: list[_Source]) -> Callable[..., Any]:
    """Compile a direct handler call from registration-time binding sources."""
    positional: list[str] = []
    keyword_sources: list[tuple[str, str]] = []
    bound_names = ["_handler"]
    bound_values: list[Any] = [handler]

    for index, (kind, name, source, payload) in enumerate(sources):
        if source == "capture":
            expression = f"captures[{payload}]"
        elif source == "body":
            expression = "body"
        else:
            expression = f"_default_{index}"
            bound_names.append(expression)
            bound_values.append(payload)

        if kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional.append(expression)
        else:
            keyword_sources.append((name, expression))

    if all(unicodedata.normalize("NFKC", name) == name for name, _ in keyword_sources):
        keyword = [f"{name}={expression}" for name, expression in keyword_sources]
    else:
        entries: list[str] = []
        for index, (name, expression) in enumerate(keyword_sources):
            key_name = f"_keyword_{index}"
            bound_names.append(key_name)
            bound_values.append(name)
            entries.append(f"{key_name}: {expression}")
        keyword = [f"**{{{', '.join(entries)}}}"]

    # Values and non-NFKC-stable names become function defaults, never source.
    arguments = ", ".join((*positional, *keyword))
    parameters = ", ".join(("captures", "body", *bound_names))
    return FunctionType(
        _shared_invoker_code(parameters, arguments),
        _INVOKER_GLOBALS,
        "invoke",
        tuple(bound_values),
    )


@dataclass(frozen=True, slots=True, init=False)
class EndpointPlan:
    """Compiled immutable handler binding and codec plan."""

    body_decoder: Any
    body_type: Any
    handler: Callable[..., Any]
    int_captures: tuple[tuple[int, str], ...]
    invoke: Callable[[list[Any], Any], Any]
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
        sources: list[_Source] = []
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
        unconsumed = [
            path_names[index] for index in range(len(path_names)) if index not in used_captures
        ]
        if unconsumed:
            raise TypeError(f"path parameter(s) {unconsumed} are not accepted by the handler")
        object.__setattr__(self, "invoke", _compile_invoker(handler, sources))

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
