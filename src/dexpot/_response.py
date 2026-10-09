"""Registration-compiled preparation for checked JSON responses.

Preparers own their output containers. The encoder sees only validated public
values; unsupported preparation shapes retain the complete native checked path.
"""

from __future__ import annotations

import copy
import math
import sys
import threading
import types
import typing
from collections.abc import Callable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from enum import Enum
from typing import Annotated, Any, NotRequired, Required, cast, get_args, get_origin, get_type_hints

import msgspec

from .requests import Request

Prepare = Callable[[Any], Any]


def _compile_graph(
    schema: Any,
    fallback: Callable[[Any], Prepare],
    infos: dict,
    records: dict,
    *,
    registration: bool,
) -> Prepare:
    """Compile field access and scalar validators once per endpoint."""
    memo: dict[Any, Prepare] = {}
    defaults_to_check: list[tuple[str, Prepare, Any]] = []
    validating_defaults = False
    deferred_defaults = 0
    builtin_factories = (list, dict, set, frozenset, tuple, bytes, str, int, float, bool)

    def inspect(annotation):
        if registration and annotation not in infos:
            infos[annotation] = type_info(annotation)
        return infos[annotation]

    def compile_type(annotation: Any) -> Prepare:
        if get_origin(annotation) in (Required, NotRequired):
            annotation = get_args(annotation)[0]
        if annotation in memo:
            return lambda value: memo[annotation](value)
        info = inspect(annotation)
        # Install a recursive reference before compiling child fields.
        memo[annotation] = lambda value: None
        prepare = build(annotation, info)
        memo[annotation] = prepare
        return prepare

    def build(annotation: Any, info: Any) -> Prepare:
        bare = annotation
        while get_origin(bare) in (Annotated, Required, NotRequired):
            bare = get_args(bare)[0]
        if isinstance(info, msgspec.inspect.AnyType):
            return dynamic
        if isinstance(info, msgspec.inspect.UnionType):
            members = tuple((inspect(a), compile_type(a)) for a in get_args(bare))
            tagged = {
                member.tag: (member, prepare)
                for member, prepare in members
                if isinstance(member, msgspec.inspect.StructType) and member.tag is not None
            }

            if all(
                not isinstance(
                    member,
                    (
                        msgspec.inspect.StructType,
                        msgspec.inspect.CollectionType,
                        msgspec.inspect.DictType,
                        msgspec.inspect.TupleType,
                        msgspec.inspect.DataclassType,
                        msgspec.inspect.TypedDictType,
                        msgspec.inspect.NamedTupleType,
                        msgspec.inspect.AnyType,
                    ),
                )
                for member, _ in members
            ):
                return native_scalar(annotation)

            def union(value: Any) -> Any:
                while isinstance(value, Enum):
                    value = value.value
                dataclass_source = is_record(value)
                if tagged and (
                    isinstance(value, (dict, msgspec.Struct, list, tuple)) or dataclass_source
                ):
                    member = next(iter(tagged.values()))[0]
                    if isinstance(value, msgspec.Struct):
                        tag = type(value).__struct_config__.tag
                    elif dataclass_source:
                        tag = (
                            getattr(value, member.tag_field, msgspec.NODEFAULT)
                            if member.tag_field is not None
                            else msgspec.NODEFAULT
                        )
                    elif isinstance(value, (list, tuple)):
                        tag = value[0] if member.array_like and value else msgspec.NODEFAULT
                    elif isinstance(value, dict):
                        tag = value.get(member.tag_field, msgspec.NODEFAULT)
                    else:
                        tag = msgspec.NODEFAULT
                    selected = tagged.get(cast(str | int, tag)) if type(tag) in (str, int) else None
                    if selected is None:
                        raise ValueError("invalid or missing union tag")
                    return selected[1](value)
                for member, branch in members:
                    if isinstance(member, msgspec.inspect.StructType) and member.tag is not None:
                        continue
                    try:
                        return branch(value)
                    except (TypeError, ValueError, msgspec.ValidationError):
                        pass
                raise ValueError("no matching response union member")

            return union
        if isinstance(info, msgspec.inspect.DictType):
            key_type, value_type = get_args(bare) or (Any, Any)
            key_prepare, value_prepare = compile_type(key_type), compile_type(value_type)

            def mapping(value: Any) -> Any:
                entries = object_items(value)
                output = {}
                for key, item in entries:
                    public_key = key_prepare(key)
                    if type(public_key) not in (str, int, float):
                        public_key = msgspec.to_builtins(public_key)
                    if type(public_key) not in (str, int, float):
                        raise TypeError("unsupported JSON object key")
                    output[public_key] = value_prepare(item)
                check_length(output, info)
                return output

            return mapping
        if isinstance(
            info,
            (
                msgspec.inspect.StructType,
                msgspec.inspect.DataclassType,
                msgspec.inspect.NamedTupleType,
                msgspec.inspect.TypedDictType,
            ),
        ):
            cls = info.cls
            is_struct = isinstance(info, msgspec.inspect.StructType)
            if registration and cls not in records:
                if is_struct:
                    annotations = {f.name: f.type for f in msgspec.structs.fields(cls)}
                else:
                    origin = get_origin(cls) or cls
                    parameters = getattr(origin, "__parameters__", ())
                    bindings = dict(zip(parameters, get_args(cls), strict=False))
                    annotations = {
                        name: substitute(hint, bindings)
                        for name, hint in get_type_hints(origin, include_extras=True).items()
                    }
                records[cls] = (
                    annotations,
                    cls.__struct_config__.omit_defaults if is_struct else False,
                )
            annotations, omit = records[cls]
            field_info = info.fields
            fields = tuple(
                (
                    f,
                    compile_type(annotations[f.name]),
                    f.default,
                )
                for f in field_info
            )
            for field, prepare, _ in fields if registration else ():
                default = field.default
                if default is msgspec.NODEFAULT:
                    if not any(field.default_factory is factory for factory in builtin_factories):
                        continue
                    default = field.default_factory()
                defaults_to_check.append((f"{cls.__name__}.{field.name}", prepare, default))
            by_name = {f.encode_name: (f, prepare, default) for f, prepare, default in fields}
            tag = info.tag if is_struct else None
            tag_field = info.tag_field if is_struct else None
            forbid_unknown = (
                info.forbid_unknown_fields
                if is_struct
                else isinstance(info, msgspec.inspect.NamedTupleType)
            )
            order = ((tag_field,) if tag is not None else ()) + tuple(by_name)
            getters = tuple(
                (field.name, field.encode_name, prepare, field) for field, prepare, _ in fields
            )

            if isinstance(info, msgspec.inspect.NamedTupleType) or (is_struct and info.array_like):

                def array(value: Any) -> Any:
                    nonlocal deferred_defaults
                    while isinstance(value, Enum):
                        value = value.value
                    if isinstance(value, Request):
                        raise TypeError("Request context cannot be serialized as a response")
                    if isinstance(value, msgspec.Struct):
                        config = type(value).__struct_config__
                        if not config.array_like:
                            raise TypeError("expected an array")
                        source = ([config.tag] if config.tag is not None else []) + [
                            getattr(value, attr) for attr in type(value).__struct_fields__
                        ]
                    elif isinstance(value, (list, tuple, set, frozenset)):
                        source = value
                    else:
                        raise TypeError("expected an array")
                    iterator = iter(source)
                    output = []
                    if tag is not None:
                        actual = next(iterator, msgspec.NODEFAULT)
                        if type(actual) is not type(tag) or actual != tag:
                            raise ValueError("invalid array tag")
                        output.append(tag)
                    for field, prepare, _ in fields:
                        item = next(iterator, msgspec.NODEFAULT)
                        if item is msgspec.NODEFAULT:
                            if field.default is not msgspec.NODEFAULT:
                                item = field.default
                            elif field.default_factory is not msgspec.NODEFAULT:
                                if validating_defaults and not any(
                                    field.default_factory is factory
                                    for factory in builtin_factories
                                ):
                                    deferred_defaults += 1
                                    continue
                                item = field.default_factory()
                            else:
                                raise ValueError("missing required array field")
                        output.append(prepare(item))
                    for extra in iterator:
                        dynamic(extra)
                        if forbid_unknown:
                            raise ValueError("unexpected array field")
                    return output

                return array

            def struct(value: Any) -> Any:
                nonlocal deferred_defaults
                if type(value) is cls and not omit:
                    output = {tag_field: tag} if tag is not None else {}
                    for attr, name, prepare, field in getters:
                        item = getattr(value, attr)
                        if item is msgspec.UNSET:
                            if field.default is not msgspec.NODEFAULT:
                                item = field.default
                            elif field.default_factory is not msgspec.NODEFAULT:
                                if validating_defaults and not any(
                                    field.default_factory is factory
                                    for factory in builtin_factories
                                ):
                                    deferred_defaults += 1
                                    continue
                                item = field.default_factory()
                            elif field.required:
                                raise ValueError("missing required field")
                            else:
                                continue
                        output[name] = prepare(item)
                    return output
                while isinstance(value, Enum):
                    value = value.value
                if isinstance(value, Request):
                    raise TypeError("Request context cannot be serialized as a response")
                if isinstance(value, msgspec.Struct):
                    source_cls = type(value)
                    if source_cls.__struct_config__.array_like:
                        raise TypeError("expected an object")
                    entries = struct_items(value)
                elif is_record(value):
                    entries = dataclass_items(value)
                elif isinstance(value, dict):
                    entries = value.items()
                else:
                    raise TypeError("expected an object")
                output = {}
                present = set()
                if tag is not None:
                    output[tag_field] = tag
                for name, item in entries:
                    if not isinstance(name, str):
                        name = dynamic(name)
                        if not isinstance(name, str):
                            raise TypeError("expected a string object key")
                    if name == tag_field and tag is not None:
                        if type(item) is not type(tag) or item != tag:
                            raise ValueError("invalid tag")
                        continue
                    field_plan = by_name.get(name)
                    if field_plan is None:
                        dynamic(item)
                        if forbid_unknown:
                            raise ValueError("unknown field")
                        continue
                    field, prepare, default = field_plan
                    present.add(name)
                    public = prepare(item)
                    if not omitted(public, default, field.default_factory, omit, wire=True):
                        output[name] = public
                for field, prepare, default in fields:
                    if field.encode_name in present:
                        continue
                    if field.default is not msgspec.NODEFAULT:
                        item = field.default
                    elif field.default_factory is not msgspec.NODEFAULT:
                        if validating_defaults and not any(
                            field.default_factory is factory for factory in builtin_factories
                        ):
                            deferred_defaults += 1
                            continue
                        item = field.default_factory()
                    elif not field.required:
                        continue
                    else:
                        raise ValueError("missing required field")
                    public = prepare(item)
                    if omit and field.default is not msgspec.NODEFAULT:
                        continue
                    if not omitted(public, default, field.default_factory, omit, wire=True):
                        output[field.encode_name] = public
                # Native Struct output follows target field order, independently
                # of mapping/source-subclass order.
                return {name: output[name] for name in order if name in output}

            return struct
        if isinstance(info, (msgspec.inspect.SetType, msgspec.inspect.FrozenSetType)):
            args = get_args(bare)
            child = compile_type(args[0] if args else Any)
            native = fallback(annotation)

            def native_set(value: Any) -> Any:
                # Preserve native hashing/deduplication semantics. Children are
                # fully prepared first, including recursively introduced defaults.
                deferred_before = deferred_defaults
                prepared = [child(item) for item in array_items(value)]
                check_length(prepared, info)
                if validating_defaults and deferred_defaults != deferred_before:
                    return prepared
                return native(prepared)

            return native_set
        if isinstance(info, (msgspec.inspect.ListType, msgspec.inspect.VarTupleType)):
            args = get_args(bare)
            child = compile_type(args[0] if args else Any)

            def sequence(value: Any) -> Any:
                output = [child(item) for item in array_items(value)]
                check_length(output, info)
                return output

            return sequence
        if isinstance(info, msgspec.inspect.TupleType):
            children = tuple(compile_type(arg) for arg in get_args(bare))

            def fixed_tuple(value: Any) -> Any:
                return [
                    prepare(item)
                    for prepare, item in zip(children, array_items(value), strict=True)
                ]

            return fixed_tuple
        if type(info) in (
            msgspec.inspect.IntType,
            msgspec.inspect.FloatType,
            msgspec.inspect.StrType,
            msgspec.inspect.BoolType,
            msgspec.inspect.NoneType,
        ):
            primitive = {
                msgspec.inspect.IntType: int,
                msgspec.inspect.FloatType: float,
                msgspec.inspect.StrType: str,
                msgspec.inspect.BoolType: bool,
                msgspec.inspect.NoneType: type(None),
            }[type(info)]
            unconstrained = all(
                getattr(info, name) is None for name in type(info).__struct_fields__
            )

            def scalar(value: Any) -> Any:
                if unconstrained and type(value) is primitive:
                    if primitive is float and not math.isfinite(value):
                        raise ValueError("non-finite floats are not supported in checked responses")
                    return value
                if isinstance(value, Request):
                    raise TypeError("Request context cannot be serialized as a response")
                value = msgspec.to_builtins(value)
                reject_nonfinite(value)
                return msgspec.convert(value, type=annotation, strict=True)

            return scalar
        if isinstance(
            info,
            (
                msgspec.inspect.BytesType,
                msgspec.inspect.ByteArrayType,
                msgspec.inspect.DateTimeType,
                msgspec.inspect.DateType,
                msgspec.inspect.TimeType,
                msgspec.inspect.TimeDeltaType,
                msgspec.inspect.UUIDType,
                msgspec.inspect.DecimalType,
                msgspec.inspect.EnumType,
                msgspec.inspect.LiteralType,
            ),
        ):
            return native_scalar(annotation)
        return fallback(annotation)

    def native_scalar(annotation: Any) -> Prepare:
        def scalar(value: Any) -> Any:
            normalized = dynamic(value)
            converted = msgspec.convert(normalized, type=annotation, strict=True)
            reject_nonfinite(converted)
            # Retain native scalar identity for omit_defaults (notably enums).
            # The encoder owns their canonical base64/temporal/UUID spelling.
            return converted

        return scalar

    def dynamic(value: Any) -> Any:
        if isinstance(value, Request):
            raise TypeError("Request context cannot be serialized as a response")
        if type(value) in (str, int, bool, type(None)):
            return value
        if isinstance(value, float):
            reject_nonfinite(value)
            return float(value)
        if isinstance(value, Enum):
            return dynamic(value.value)
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                public_key = dynamic(key)
                if type(public_key) not in (str, int, float):
                    raise TypeError("unsupported JSON object key")
                output[public_key] = dynamic(item)
            return output
        if isinstance(value, (list, tuple, set, frozenset)):
            return [dynamic(item) for item in value]
        if isinstance(value, msgspec.Struct):
            cls = type(value)
            config = cls.__struct_config__
            if config.array_like:
                return ([config.tag] if config.tag is not None else []) + [
                    dynamic(getattr(value, attr)) for attr in cls.__struct_fields__
                ]
            return {name: dynamic(item) for name, item in struct_items(value)}
        if is_record(value):
            return {name: dynamic(item) for name, item in dataclass_items(value)}
        result = msgspec.to_builtins(value)
        reject_nonfinite(result)
        return result

    def dataclass_items(value: Any) -> Any:
        fields = dataclass_fields(value) if is_dataclass(value) else type(value).__attrs_attrs__
        for field in fields:
            item = getattr(value, field.name)
            if item is not msgspec.UNSET:
                yield field.name, item

    def object_items(value: Any) -> Any:
        while isinstance(value, Enum):
            value = value.value
        if isinstance(value, Request):
            raise TypeError("Request context cannot be serialized as a response")
        if isinstance(value, dict):
            return value.items()
        if isinstance(value, msgspec.Struct) and not type(value).__struct_config__.array_like:
            return struct_items(value)
        if is_record(value):
            return dataclass_items(value)
        raise TypeError("expected an object")

    def array_items(value: Any) -> Any:
        while isinstance(value, Enum):
            value = value.value
        if isinstance(value, Request):
            raise TypeError("Request context cannot be serialized as a response")
        if isinstance(value, (list, tuple, set, frozenset)):
            return iter(value)
        if isinstance(value, msgspec.Struct) and type(value).__struct_config__.array_like:
            config = type(value).__struct_config__
            return iter(
                ([config.tag] if config.tag is not None else [])
                + [getattr(value, attr) for attr in type(value).__struct_fields__]
            )
        raise TypeError("expected an array")

    def struct_items(value: Any) -> Any:
        cls = type(value)
        config = cls.__struct_config__
        if config.tag is not None:
            yield config.tag_field, config.tag
        names = cls.__struct_fields__
        defaults = (msgspec.NODEFAULT,) * (
            len(names) - len(cls.__struct_defaults__)
        ) + cls.__struct_defaults__
        for name, attr, default in zip(cls.__struct_encode_fields__, names, defaults, strict=True):
            raw = getattr(value, attr)
            if raw is msgspec.UNSET:
                continue
            factory = getattr(default, "factory", msgspec.NODEFAULT)
            if omitted(raw, default, factory, config.omit_defaults):
                # Omission must never hide protected identities.
                dynamic(raw)
                continue
            yield name, raw

    prepared = compile_type(schema)
    # Defaults inside a native fallback still belong to the endpoint contract.
    seen_info: set[int] = set()

    def visit_defaults(info: Any) -> None:
        if id(info) in seen_info:
            return
        seen_info.add(id(info))
        if isinstance(info, (msgspec.inspect.StructType, msgspec.inspect.DataclassType)):
            compile_type(info.cls)
        if isinstance(info, msgspec.Struct):
            for name in type(info).__struct_fields__:
                if name not in ("cls", "default", "default_factory"):
                    visit_defaults(getattr(info, name))
        elif isinstance(info, (tuple, list)):
            for item in info:
                visit_defaults(item)

    if not registration:
        return prepared
    visit_defaults(inspect(schema))
    validating_defaults = True
    try:
        for name, prepare, default in defaults_to_check:
            try:
                prepare(default)
            except (TypeError, ValueError, msgspec.ValidationError, RecursionError) as exc:
                raise TypeError(f"invalid checked response default for {name}") from exc
    finally:
        validating_defaults = False
    return prepared


def _metadata_copy(value, memo):
    """Clone trusted inspect descriptors only; keep user types/default identities."""
    if id(value) in memo:
        return memo[id(value)]
    if isinstance(value, msgspec.Struct) and type(value).__module__ == "msgspec.inspect":
        out = copy.copy(value)
        memo[id(value)] = out
        for name in type(value).__struct_fields__:
            if name not in ("cls", "default", "default_factory"):
                msgspec.structs.force_setattr(out, name, _metadata_copy(getattr(value, name), memo))
        return out
    if isinstance(value, tuple):
        out = tuple(_metadata_copy(item, memo) for item in value)
        memo[id(value)] = out
        return out
    if isinstance(value, list):
        out = []
        memo[id(value)] = out
        out.extend(_metadata_copy(item, memo) for item in value)
        return out
    return value


class PreparationBinding:
    def __init__(self, schema, fallback):
        self.schema = schema
        self.infos = {}
        self.records = {}
        self.fallbacks = {}

        def capture(annotation):
            if annotation not in self.fallbacks:
                self.fallbacks[annotation] = fallback(annotation)
            return self.fallbacks[annotation]

        self.canonical = _compile_graph(
            schema, capture, self.infos, self.records, registration=True
        )

    def bind(self):
        memo = {}
        infos = {annotation: _metadata_copy(info, memo) for annotation, info in self.infos.items()}
        records = {cls: (dict(fields), omit) for cls, (fields, omit) in self.records.items()}
        return _compile_graph(
            self.schema, self.fallbacks.__getitem__, infos, records, registration=False
        )


def compile_binding(schema, fallback):
    return PreparationBinding(schema, fallback)


def compile_preparer(schema: Any, fallback: Callable[[Any], Prepare]) -> Prepare:
    factory = compile_binding(schema, fallback)
    if getattr(sys, "_is_gil_enabled", lambda: True)():
        return factory.canonical
    local = threading.local()

    def prepare(value):
        if not hasattr(local, "prepare"):
            local.prepare = factory.bind()
        return local.prepare(value)

    # Apply only to graph-shaped contracts on free-threaded Darwin. Flat
    # contracts keep the same owned preparation path without policy syscalls.
    from ._preparation_policy import darwin_policy, scoped_preparer

    primitive_infos = (
        msgspec.inspect.IntType,
        msgspec.inspect.FloatType,
        msgspec.inspect.StrType,
        msgspec.inspect.BoolType,
        msgspec.inspect.NoneType,
    )
    root = factory.infos[schema]
    flat_struct = isinstance(root, msgspec.inspect.StructType) and all(
        type(field.type) in primitive_infos for field in root.fields
    )
    if (
        flat_struct
        and all(
            field.default is msgspec.NODEFAULT and field.default_factory is msgspec.NODEFAULT
            for field in root.fields
        )
        and getattr(schema, "__post_init__", None) is None
        and sys.platform == "darwin"
        and not getattr(sys, "_is_gil_enabled", lambda: True)()
    ):
        # The native checked codec preserves the flat-contract compatibility
        # path rather than making every tiny response a Python graph walk.
        return fallback(schema)
    flat = type(root) in primitive_infos or flat_struct
    policy = None if flat else darwin_policy()
    bound_prepare = prepare
    if policy is not None:
        guarded = scoped_preparer(bound_prepare, policy)

        def prepare(value):
            return guarded(value)

    return prepare


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
