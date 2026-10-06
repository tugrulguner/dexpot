"""Immutable application and routing plans compiled before serving traffic."""

from __future__ import annotations

import inspect
import math
import typing
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from functools import lru_cache, partial, partialmethod
from threading import Lock
from types import CodeType, FunctionType, MappingProxyType
from typing import Any

import msgspec

from .requests import Request

_json_encode = msgspec.json.encode

_Source = tuple[Any, str, str, Any]
_INVOKER_GLOBALS: dict[str, Any] = {}
_INVOKER_CODE_LOCK = Lock()


class _ApplicationCompilationDuringRegistration(RuntimeError):
    """Keep registration-control failures visible during annotation evaluation."""


def _unwrap_handler(handler: Any, *, stop_at_signature: bool = False) -> Any:
    stop = (lambda value: hasattr(value, "__signature__")) if stop_at_signature else None
    try:
        return inspect.unwrap(handler, stop=stop)
    except (TypeError, ValueError) as exc:
        raise TypeError("handler signature cannot be inspected") from exc


def _is_async_handler(handler: Callable[..., Any]) -> bool:
    """Detect asynchronous callables without adding request-path inspection."""

    seen: set[int] = set()

    def visit(value: Any) -> bool:
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)

        if inspect.iscoroutinefunction(value) or inspect.isasyncgenfunction(value):
            return True
        if isinstance(value, partial) and visit(value.func):
            return True
        # Unbound partialmethod accessors are ordinary functions on CPython 3.12.
        method = getattr(value, "__partialmethod__", getattr(value, "_partialmethod", None))
        if isinstance(method, partialmethod) and visit(method.func):
            return True

        wrapped = getattr(value, "__wrapped__", value)
        if wrapped is not value and visit(wrapped):
            return True
        _unwrap_handler(value)

        if inspect.isclass(value):
            return any(
                visit(lifecycle)
                for lifecycle in (type(value).__call__, value.__new__, value.__init__)
            )
        if inspect.isroutine(value) or not callable(value):
            return False
        return visit(value.__call__)

    return visit(handler)


def _class_annotation_owner(handler: type) -> Any:
    """Mirror inspect.signature's metaclass/MRO constructor precedence."""

    def user_method(cls: type, name: str) -> Any:
        method = getattr(cls, name)
        target = _unwrap_handler(method, stop_at_signature=True)
        seen: set[int] = set()
        while not hasattr(target, "__signature__"):
            descriptor = getattr(
                target, "__partialmethod__", getattr(target, "_partialmethod", None)
            )
            if not isinstance(descriptor, partialmethod):
                break
            if id(target) in seen:
                raise TypeError("handler signature cannot be inspected")
            seen.add(id(target))
            target = _unwrap_handler(descriptor.func, stop_at_signature=True)
        if inspect.isbuiltin(target) or inspect.ismethoddescriptor(target):
            return None
        return target

    call = user_method(type(handler), "__call__")
    if call is not None:
        return _unwrap_handler(call, stop_at_signature=True)
    new = user_method(handler, "__new__")
    init = user_method(handler, "__init__")
    for base in handler.__mro__:
        if new is not None and "__new__" in base.__dict__:
            return _unwrap_handler(new, stop_at_signature=True)
        if init is not None and "__init__" in base.__dict__:
            return _unwrap_handler(init, stop_at_signature=True)
    return handler


def _annotation_owner(handler: Callable[..., Any]) -> Any:
    """Return the function that owns a callable's annotation namespace."""
    owner = _unwrap_handler(handler, stop_at_signature=True)
    if isinstance(owner, partial):
        owner = _unwrap_handler(owner.func, stop_at_signature=True)
    if inspect.isclass(owner) and getattr(owner, "__signature__", None) is None:
        owner = _class_annotation_owner(owner)
    if not inspect.isroutine(owner) and not inspect.isclass(owner):
        owner = owner.__call__
        if isinstance(owner, partial):
            owner = owner.func
        owner = _unwrap_handler(owner, stop_at_signature=True)
    return getattr(owner, "__func__", owner)


def _handler_signature(handler: Callable[..., Any]) -> inspect.Signature:
    """Inspect a handler with one stable registration diagnostic."""
    try:
        return inspect.signature(handler)
    except (TypeError, ValueError) as exc:
        raise TypeError("handler signature cannot be inspected") from exc


def _type_hints(
    fn: Any,
    signature: inspect.Signature,
    localns: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw = {name: parameter.annotation for name, parameter in signature.parameters.items()}
    resolved: dict[str, Any] = {}
    owner = _annotation_owner(fn)
    globalns = getattr(owner, "__globals__", {})
    closure = getattr(owner, "__closure__", None) or ()
    code = getattr(owner, "__code__", None)
    cell_names = code.co_freevars if code is not None else ()
    cells = dict(zip(cell_names, (cell.cell_contents for cell in closure), strict=True))
    for name, annotation in raw.items():
        if isinstance(annotation, str):
            try:
                annotation = eval(
                    annotation,
                    dict(typing.__dict__),
                    {**globalns, **(localns or {}), **cells},
                )
            except _ApplicationCompilationDuringRegistration:
                raise
            except Exception:
                pass
        resolved[name] = annotation
    return resolved


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
    resp_decoder: Any
    resp_convert: Any
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
        if _is_async_handler(handler):
            raise TypeError("asynchronous handlers are not supported")
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

        if resp_type is not None:
            _validate_response_schema(msgspec.inspect.type_info(resp_type), set())
        object.__setattr__(
            self,
            "resp_decoder",
            msgspec.json.Decoder(resp_type, strict=True) if resp_type is not None else None,
        )
        object.__setattr__(
            self,
            "resp_convert",
            partial(msgspec.convert, type=resp_type, strict=True)
            if resp_type is not None
            else None,
        )

        signature = _handler_signature(handler)
        hints = _type_hints(handler, signature, annotation_locals)
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
            if isinstance(annotation, str) and not (
                body_type is not None and not body_param_seen and name not in captures_by_name
            ):
                raise TypeError(
                    f"cannot resolve annotation for '{name}'; supply annotation_locals "
                    "with the original bindings or use concrete annotations"
                )
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
        if isinstance(result, Request) or (
            (self.needs_request or self.resp_type is not None) and _contains_request(result, set())
        ):
            raise TypeError("Request context cannot be serialized as a response")
        if self.resp_type is not None:
            normalized = msgspec.to_builtins(result)
            _reject_nonfinite(normalized)
            projected = self.resp_convert(normalized)
            # Conversion may introduce defaults that were absent from the
            # application value. Check them before normalization erases Request
            # identities, then project default values through the schema too.
            if _contains_request(projected, set()):
                raise TypeError("Request context cannot be serialized as a response")
            normalized_defaults = msgspec.to_builtins(projected)
            _reject_nonfinite(normalized_defaults)
            projected = self.resp_convert(normalized_defaults)
            encoded = self.resp_encoder.encode(projected)
            self.resp_decoder.decode(encoded)
            return encoded
        return _json_encode(result)


def _validate_response_schema(info: Any, seen: set[int]) -> None:
    """Inspect once at registration, including recursive schema graphs."""
    if id(info) in seen:
        return
    seen.add(id(info))
    if isinstance(info, msgspec.inspect.CustomType):
        raise TypeError("custom types are not supported in checked responses")
    cls = getattr(info, "cls", None)
    if cls is Request or (
        cls is not None and (hasattr(cls, "__post_init__") or hasattr(cls, "__attrs_post_init__"))
    ):
        raise TypeError("Request and post-init hooks are not supported in checked response schemas")
    if isinstance(info, msgspec.Struct):
        for name in type(info).__struct_fields__:
            if name not in ("cls", "default", "default_factory"):
                _validate_response_schema(getattr(info, name), seen)
    elif isinstance(info, (tuple, list)):
        for item in info:
            _validate_response_schema(item, seen)
    if isinstance(info, msgspec.inspect.StructType):
        # Encoders can omit defaults, and decoders reuse them without checking.
        # Reject invalid static/known-builtin defaults once at registration.
        # Never execute an application factory while registering a schema.
        builtin_factories = (list, dict, set, frozenset, tuple, bytes, str, int, float, bool)
        assert cls is not None
        for field in msgspec.structs.fields(cls):
            default = field.default
            if default is msgspec.NODEFAULT:
                if not any(field.default_factory is factory for factory in builtin_factories):
                    continue
                default = field.default_factory()
            try:
                if _contains_request(default, set()):
                    raise TypeError("Request context is not a response default")
                normalized = msgspec.to_builtins(default)
                _reject_nonfinite(normalized)
                converted = msgspec.convert(normalized, type=field.type, strict=True)
                msgspec.json.decode(msgspec.json.encode(converted), type=field.type, strict=True)
            except (TypeError, ValueError, msgspec.ValidationError, RecursionError) as exc:
                raise TypeError(
                    f"invalid checked response default for {cls.__name__}.{field.name}"
                ) from exc


def _reject_nonfinite(value: Any) -> None:
    """Reject floats that JSON encoding would otherwise silently turn into null."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite floats are not supported in checked responses")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite(key)
            _reject_nonfinite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_nonfinite(item)


def _contains_request(value: Any, seen: set[int]) -> bool:
    """Find a Request nested in response shapes supported by msgspec JSON."""
    if isinstance(value, Request):
        return True
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        return False
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
            _contains_request(getattr(value, name), seen) for name in type(value).__struct_fields__
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
