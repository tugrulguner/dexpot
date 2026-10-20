"""Registration-compiled projection for a narrow required nested Struct graph.

The selected incumbent owns every unsupported case. Class guards are not an
atomic schema transaction; captured slot getters prevent new descriptor
callbacks during a capture after those guards have been checked.
"""

import math
from collections.abc import Callable, Mapping
from types import MemberDescriptorType
from typing import Any

import msgspec


class _Miss(Exception):
    pass


_PRIMITIVES = {
    msgspec.inspect.StrType: str,
    msgspec.inspect.IntType: int,
    msgspec.inspect.FloatType: float,
    msgspec.inspect.BoolType: bool,
    msgspec.inspect.NoneType: type(None),
}


def _namespace(cls: Any) -> Any:
    return type.__getattribute__(cls, "__dict__")


def compile_direct(
    schema: Any, fallback: Any, *, infos: Mapping[Any, Any] | None = None
) -> tuple[Callable[..., Any] | None, bool]:
    """Compile once from registration metadata; bind private executable state."""
    plans: dict[Any, Any] = {}
    visiting: set[Any] = set()
    guards: list[Any] = []
    mros: list[Any] = []
    descriptors: dict[Any, Any] = {}
    missing = object()

    def inspect(cls: Any) -> None:
        if type(cls) is not type(msgspec.Struct):
            raise TypeError("unsupported class")
        if cls in visiting:
            raise TypeError("recursive contract")
        if cls in plans:
            return
        visiting.add(cls)
        info = infos.get(cls) if infos is not None else msgspec.inspect.type_info(cls)
        if not isinstance(info, msgspec.inspect.StructType):
            raise TypeError("no frozen Struct metadata")
        cfg = cls.__struct_config__
        if (
            info.tag is not None
            or info.array_like
            or cfg.omit_defaults
            or cfg.dict
            or cfg.forbid_unknown_fields
        ):
            raise TypeError("unsupported Struct config")
        if cls.__getattribute__ is not msgspec.Struct.__getattribute__:
            raise TypeError("custom access")
        if getattr(cls, "__getattr__", None) is not None:
            raise TypeError("custom missing-field access")
        mro = type.__getattribute__(cls, "__mro__")
        mros.append((cls, mro))
        for owner in mro:
            namespace = _namespace(owner)
            for name in ("__getattribute__", "__getattr__"):
                guards.append((owner, name, namespace.get(name, missing)))
        plans[cls] = ()
        fields = []
        for index, field in enumerate(info.fields):
            if (
                field.default is not msgspec.NODEFAULT
                or field.default_factory is not msgspec.NODEFAULT
            ):
                raise TypeError("defaults unsupported")
            descriptor = next(
                (_namespace(owner)[field.name] for owner in mro if field.name in _namespace(owner)),
                None,
            )
            if type(descriptor) is not MemberDescriptorType:
                raise TypeError("custom descriptor")
            descriptors[cls, index] = descriptor
            for owner in mro:
                namespace = _namespace(owner)
                guards.append((owner, field.name, namespace.get(field.name, missing)))
            ann = field.type
            if isinstance(ann, msgspec.inspect.StructType):
                child = ann.cls
                inspect(child)
                fields.append((field.encode_name, child))
            elif isinstance(ann, msgspec.inspect.ListType):
                if ann.min_length is not None or ann.max_length is not None:
                    raise TypeError("constrained list")
                if not isinstance(ann.item_type, msgspec.inspect.StructType):
                    raise TypeError("only list[Struct]")
                child = ann.item_type.cls
                inspect(child)
                fields.append((field.encode_name, ("list", child)))
            else:
                primitive = _PRIMITIVES.get(type(ann))
                if primitive is None or any(
                    getattr(ann, name) is not None for name in type(ann).__struct_fields__
                ):
                    raise TypeError("unsupported or constrained primitive")
                fields.append((field.encode_name, primitive))
        plans[cls] = tuple(fields)
        visiting.remove(cls)

    root_info = infos.get(schema) if infos is not None else msgspec.inspect.type_info(schema)
    root_list = isinstance(root_info, msgspec.inspect.ListType)
    if isinstance(root_info, msgspec.inspect.StructType) and all(
        type(field.type) in _PRIMITIVES for field in root_info.fields
    ):
        return None, False
    if root_list and (root_info.min_length is not None or root_info.max_length is not None):
        return None, False
    root_cls = getattr(root_info.item_type, "cls", None) if root_list else schema
    try:
        inspect(root_cls)
    except (TypeError, AttributeError):
        return None, False

    indices = {cls: index for index, cls in enumerate(plans)}
    constants: dict[str, Any] = {
        "fallback": fallback,
        "type": type,
        "_Miss": _Miss,
        "_finite": math.isfinite,
    }
    getter_bindings: dict[str, Any] = {}
    source = ["def _mro(cls): return type.__getattribute__(cls, '__mro__')"]
    for cls, serial in indices.items():
        constants[f"c{serial}"] = cls
        source.extend(
            [f"def s{serial}(v):", f"    if type(v) is not c{serial}: raise _Miss", "    o = {}"]
        )
        for index, (key, typ) in enumerate(plans[cls]):
            getter_bindings[f"g{serial}_{index}"] = descriptors[cls, index]
            source.append(f"    x{index} = g{serial}_{index}(v)")
            if isinstance(typ, tuple):
                child = indices[typ[1]]
                source.extend(
                    [
                        f"    if type(x{index}) is not list: raise _Miss",
                        f"    y{index} = []",
                        f"    for e{index} in x{index}:",
                        f"        y{index}.append(s{child}(e{index}))",
                        f"    o[{key!r}] = y{index}",
                    ]
                )
            elif typ in (str, int, float, bool, type(None)):
                constants[f"t{serial}_{index}"] = typ
                source.append(f"    if type(x{index}) is not t{serial}_{index}: raise _Miss")
                if typ is float:
                    source.append(f"    if not _finite(x{index}): raise _Miss")
                source.append(f"    o[{key!r}] = x{index}")
            else:
                source.append(f"    o[{key!r}] = s{indices[typ]}(x{index})")
        source.append("    return o")
    body = (
        "        if type(v) is not list: raise _Miss\n        return [s0(e) for e in v]"
        if root_list
        else "        return s0(v)"
    )
    source.append(
        "def prepare(v):\n"
        "    for mapping, name, expected in _guards:\n"
        "        if mapping.get(name, _missing) is not expected: return fallback(v)\n"
        "    for cls, mro in _mros:\n"
        "        if _mro(cls) is not mro: return fallback(v)\n"
        "    try:\n" + body + "\n"
        "    except (_Miss, AttributeError):\n"
        "        return fallback(v)"
    )
    code = compile("\n".join(source), "<nested-direct-preparation>", "exec")

    def bind(fallback_override: Any = None) -> Any:
        private = constants.copy()
        private_missing = object()
        private["_missing"] = private_missing
        private["_guards"] = tuple(
            (_namespace(owner), name, private_missing if expected is missing else expected)
            for owner, name, expected in guards
        )
        private["_mros"] = tuple((cls, mro) for cls, mro in mros)
        for name, descriptor in getter_bindings.items():
            private[name] = descriptor.__get__
        if fallback_override is not None:
            private["fallback"] = fallback_override
        exec(code, private)
        prepared = private["prepare"]
        prepared.__direct_preparation__ = True
        return prepared

    return bind, True
