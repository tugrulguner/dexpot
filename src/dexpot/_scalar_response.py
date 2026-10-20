"""Conservative straight-line primitive projection; all other values use incumbent."""

import math
import sys
import threading
from types import FunctionType, MemberDescriptorType
from typing import Any, cast

import msgspec


def compile_scalar(schema, fallback):
    # Keep the incumbent GIL path: measured benefit is specific to FT.
    if getattr(sys, "_is_gil_enabled", lambda: True)():
        return fallback
    info = msgspec.inspect.type_info(schema)
    if not isinstance(info, msgspec.inspect.StructType):
        return fallback
    if info.array_like or info.tag is not None or schema.__struct_config__.dict:
        return fallback
    if schema.__getattribute__ is not msgspec.Struct.__getattribute__:
        return fallback
    primitive = {
        msgspec.inspect.IntType: int,
        msgspec.inspect.StrType: str,
        msgspec.inspect.FloatType: float,
        msgspec.inspect.BoolType: bool,
        msgspec.inspect.NoneType: type(None),
    }
    fields = []
    for field in info.fields:
        kind = primitive.get(type(field.type))
        if (
            kind is None
            or field.default is not msgspec.NODEFAULT
            or field.default_factory is not msgspec.NODEFAULT
        ):
            return fallback
        # Metadata constraints are not erased by this fast path.
        if any(
            getattr(field.type, name, None) is not None
            for name in (
                "gt",
                "ge",
                "lt",
                "le",
                "multiple_of",
                "min_length",
                "max_length",
                "pattern",
            )
        ):
            return fallback
        fields.append((field.name, field.encode_name, kind))
    namespace = {
        "schema": schema,
        "fallback": fallback,
        "type": type,
        "finite": math.isfinite,
        "base_access": msgspec.Struct.__getattribute__,
    }
    code = [
        "def prepare(value):",
        "    if type(value) is not schema or schema.__getattribute__ is not base_access: return fallback(value)",
    ]
    for index, (name, _wire, kind) in enumerate(fields):
        descriptor = getattr(schema, name, None)
        if type(descriptor) is not MemberDescriptorType:
            return fallback
        namespace[f"d{index}"] = descriptor
        namespace[f"g{index}"] = descriptor.__get__
        namespace["UnsetField"] = AttributeError
        namespace[f"t{index}"] = kind
        code.extend(
            [
                f"    if getattr(schema,{name!r},None) is not d{index}: return fallback(value)",
                f"    try: v{index}=g{index}(value)",
                "    except UnsetField: return fallback(value)",
                f"    if type(v{index}) is not t{index}: return fallback(value)",
            ]
        )
        if kind is float:
            code.append(
                f'    if not finite(v{index}): raise ValueError("non-finite floats are not supported in JSON responses")'
            )
    code.append(
        "    return {"
        + ", ".join(f"{wire!r}:v{index}" for index, (_, wire, _) in enumerate(fields))
        + "}"
    )
    namespace["getattr"] = getattr
    exec(compile("\n".join(code), "dexpot-scalar-projection", "exec"), namespace)
    canonical = namespace["prepare"].__code__
    local = threading.local()

    def prepare(value):
        bound = getattr(local, "prepare", None)
        if bound is None:
            bound = FunctionType(canonical, namespace.copy(), "prepare")
            local.prepare = bound
        return bound(value)

    cast(Any, prepare).__compiled_scalar__ = True
    return prepare
