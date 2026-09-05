"""Immutable application and routing plans compiled before serving traffic."""

from __future__ import annotations

import inspect
import typing
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from functools import lru_cache
from threading import Lock
from types import CodeType, FunctionType, MappingProxyType
from typing import Any

import msgspec

from .requests import Request

_json_encode = msgspec.json.encode

_type_hints_cache: dict[Any, dict[str, Any]] = {}

_Source = tuple[Any, str, str, Any]
_INVOKER_GLOBALS: dict[str, Any] = {}
_INVOKER_CODE_LOCK = Lock()


class _ApplicationCompilationDuringRegistration(RuntimeError):
    """Keep registration-control failures visible during annotation evaluation."""


def _type_hints(fn: Any, localns: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
                    annotation = eval(
                        annotation,
                        dict(typing.__dict__),
                        {**globalns, **cells, **(localns or {})},
                    )
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
        elif source == "request":
            expression = "request"
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
    request_parameters = ("request",) if any(source[2] == "request" for source in sources) else ()
    parameters = ", ".join(("captures", "body", *request_parameters, *bound_names))
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
    invoke: Callable[..., Any]
    method: str
    needs_request: bool
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
        annotation_locals: Mapping[str, Any] | None = None,
    ) -> None:
        if body_type is Request:
            raise TypeError("Request is handler context and cannot be used as a body type")
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

        hints = _type_hints(handler, annotation_locals)
        signature = inspect.signature(handler)
        captures_by_name = {name: index for index, name in enumerate(path_names)}
        sources: list[_Source] = []
        int_captures: list[tuple[int, str]] = []
        used_captures: set[int] = set()
        body_param_seen = False
        needs_request = False

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
                if annotation is Request:
                    raise TypeError(f"path parameter '{name}' cannot also be annotated as Request")
                index = captures_by_name[name]
                if annotation is int:
                    int_captures.append((index, name))
                sources.append((parameter.kind, name, "capture", index))
                used_captures.add(index)
            elif annotation is Request:
                needs_request = True
                sources.append((parameter.kind, name, "request", None))
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
        object.__setattr__(self, "needs_request", needs_request)
        unconsumed = [
            path_names[index] for index in range(len(path_names)) if index not in used_captures
        ]
        if unconsumed:
            raise TypeError(f"path parameter(s) {unconsumed} are not accepted by the handler")
        object.__setattr__(self, "invoke", _compile_invoker(handler, sources))

    def encode(self, result: Any) -> bytes:
        """Encode a successful result using the endpoint response contract."""
        if isinstance(result, Request) or (self.needs_request and _contains_request(result, set())):
            raise TypeError("Request context cannot be serialized as a response")
        if self.resp_encoder is not None and type(result) is self.resp_type:
            return self.resp_encoder.encode(result)
        return _json_encode(result)


def _contains_request(value: Any, seen: set[int]) -> bool:
    """Find a Request nested in response shapes supported by msgspec JSON."""
    if isinstance(value, Request):
        return True
    dataclass_instance = is_dataclass(value) and not isinstance(value, type)
    if not dataclass_instance and not isinstance(
        value, (Mapping, list, tuple, set, frozenset, msgspec.Struct, Enum)
    ):
        return False
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    if isinstance(value, Enum):
        return _contains_request(value.value, seen)
    if is_dataclass(value) and not isinstance(value, type):
        return any(_contains_request(getattr(value, field.name), seen) for field in fields(value))
    if isinstance(value, Mapping):
        return any(_contains_request(item, seen) for pair in value.items() for item in pair)
    if isinstance(value, msgspec.Struct):
        return any(
            _contains_request(getattr(value, field.name), seen)
            for field in msgspec.structs.fields(type(value))
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_request(item, seen) for item in value)
    return False


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
