"""Registration-time OpenAPI snapshots and detached document generation."""

from __future__ import annotations

import ast
import builtins
import inspect
import math
import re
import sys
import typing
import weakref
from collections import abc
from dataclasses import is_dataclass
from threading import RLock
from types import ModuleType
from typing import Any

import msgspec

from ._inputs import _MISSING
from ._plans import _ApplicationCompilationDuringRegistration

_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_MODEL_LOCK = RLock()
_MODEL_SCHEMAS: dict[int, tuple[weakref.ReferenceType[Any], bytes]] = {}


def _model(tp: Any) -> bool:
    return isinstance(tp, type) and (
        issubclass(tp, msgspec.Struct)
        or is_dataclass(tp)
        or hasattr(tp, "__attrs_attrs__")
        or (issubclass(tp, dict) and hasattr(tp, "__total__"))
        or (issubclass(tp, tuple) and hasattr(tp, "_fields"))
    )


def _forget_model(key: int, reference: weakref.ReferenceType[Any]) -> None:
    with _MODEL_LOCK:
        entry = _MODEL_SCHEMAS.get(key)
        if entry is not None and entry[0] is reference:
            del _MODEL_SCHEMAS[key]


def _remember_models(seen: dict[int, Any]) -> None:
    # Native decoders retain their first model bindings process-wide. Compare
    # resolved schema graphs, not raw strings, so alias rebinding is visible too.
    candidates = []
    for tp in seen.values():
        if _model(tp):
            schemas, components = msgspec.json.schema_components([tp])
            candidates.append((tp, msgspec.json.encode((schemas, components))))
    with _MODEL_LOCK:
        for tp, encoded in candidates:
            previous = _MODEL_SCHEMAS.get(id(tp))
            if previous is not None and previous[0]() is tp and previous[1] != encoded:
                raise TypeError("OpenAPI model metadata changed after its first captured binding")
        for tp, encoded in candidates:
            key = id(tp)
            reference = weakref.ref(tp, lambda ref, key=key: _forget_model(key, ref))
            _MODEL_SCHEMAS[key] = (reference, encoded)


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("non-finite floats cannot be represented in OpenAPI")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def _ordinary_attribute_access(owner: Any) -> None:
    base = type if isinstance(owner, type) else ModuleType
    if inspect.getattr_static(type(owner), "__getattribute__") is not inspect.getattr_static(
        base, "__getattribute__"
    ):
        raise TypeError("OpenAPI requires declarative schema annotations; opaque attribute access")


def _module_namespace(module: ModuleType | None) -> dict[str, Any]:
    if module is None:
        return {}
    _ordinary_attribute_access(module)
    if inspect.getattr_static(type(module), "__dict__") is not inspect.getattr_static(
        ModuleType, "__dict__"
    ):
        raise TypeError("OpenAPI requires declarative schema annotations; opaque module namespace")
    return vars(module)


def _declarative(tp: Any, seen: dict[int, Any], namespace: dict[str, Any] | None = None) -> None:
    """Reject calls in type-position forward references, not Literal/metadata strings."""
    namespace = namespace or {}
    if isinstance(tp, typing.ForwardRef):
        module = sys.modules.get(tp.__forward_module__ or "")
        if module is not None:
            parameters = namespace.get("__type_params__", ())
            namespace = {**{p.__name__: p for p in parameters}, **_module_namespace(module)}
        tp = tp.__forward_arg__
    if isinstance(tp, str):
        tree = ast.parse(tp, mode="eval")
        if any(isinstance(node, ast.Call) for node in ast.walk(tree)):
            raise TypeError(
                "OpenAPI requires declarative schema annotations; construct constrained aliases eagerly"
            )

        missing = object()

        def unsupported() -> typing.NoReturn:
            raise TypeError(
                "OpenAPI requires declarative schema annotations; unsupported type expression"
            )

        def lookup(node: ast.AST) -> Any:
            if isinstance(node, ast.Name):
                if node.id in namespace:
                    return namespace[node.id]
                return vars(builtins).get(node.id, missing)
            if isinstance(node, ast.Attribute):
                owner = lookup(node.value)
                if isinstance(owner, (ModuleType, type)):
                    _ordinary_attribute_access(owner)
                    # Static lookup follows inherited aliases without invoking descriptors.
                    resolved = inspect.getattr_static(owner, node.attr, missing)
                    if (
                        isinstance(owner, type)
                        and inspect.getattr_static(type(resolved), "__get__", missing)
                        is not missing
                    ):
                        unsupported()
                    return resolved
            if isinstance(node, ast.Subscript):
                owner = lookup(node.value)
                key = node.slice
                if type(owner) in (dict, list, tuple) and isinstance(key, ast.Constant):
                    if type(key.value) not in (str, int):
                        unsupported()
                    if type(owner) is dict and any(type(k) not in (str, int) for k in owner):
                        unsupported()
                    try:
                        return owner[key.value]
                    except (KeyError, IndexError, TypeError):
                        unsupported()
            return missing

        special = tuple(
            getattr(typing, name, missing)
            for name in (
                "Union",
                "Optional",
                "Required",
                "NotRequired",
                "ReadOnly",
                "ClassVar",
                "Final",
                "Unpack",
            )
        )
        extensions = sys.modules.get("typing_extensions")
        if extensions is not None:
            special += tuple(
                vars(extensions).get(name, missing)
                for name in ("Required", "NotRequired", "ReadOnly", "Unpack")
            )
        containers = (
            list,
            dict,
            tuple,
            set,
            frozenset,
            abc.Sequence,
            abc.MutableSequence,
            abc.Mapping,
            abc.MutableMapping,
            abc.Set,
            abc.MutableSet,
        )
        generic_getitem = inspect.getattr_static(typing.Generic, "__class_getitem__")

        def visit(node: ast.AST) -> None:
            value = lookup(node)
            if value is not missing:
                if isinstance(value, (property, staticmethod, classmethod)):
                    unsupported()
                _declarative(value, seen, namespace)
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    _declarative(node.value, seen, namespace)
                elif node.value is not None and node.value is not Ellipsis:
                    unsupported()
            elif isinstance(node, ast.Subscript):
                root = lookup(node.value)
                if root is missing:
                    unsupported()
                if root is typing.Literal:
                    return
                if root is typing.Annotated and isinstance(node.slice, ast.Tuple):
                    visit(node.slice.elts[0])
                    # Metadata strings are values, never forward references.
                    for metadata in node.slice.elts[1:]:
                        try:
                            ast.literal_eval(metadata)
                        except (ValueError, TypeError, SyntaxError):
                            resolved = lookup(metadata)
                            if resolved is missing or isinstance(
                                resolved, (property, staticmethod, classmethod)
                            ):
                                unsupported()
                    return
                origin = typing.get_origin(root)
                if not (
                    any(root is item or origin is item for item in containers + special)
                    or isinstance(root, typing.TypeAliasType)
                    or (
                        isinstance(root, type)
                        and inspect.getattr_static(root, "__class_getitem__", missing)
                        is generic_getitem
                    )
                ):
                    unsupported()
                _declarative(root, seen, namespace)
                visit(node.slice)
            elif isinstance(node, ast.Tuple):
                for child in node.elts:
                    visit(child)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                for child in (node.left, node.right):
                    value = lookup(child)
                    if isinstance(value, type) and any(
                        inspect.getattr_static(type(value), name, missing)
                        is not inspect.getattr_static(type, name)
                        for name in ("__or__", "__ror__")
                    ):
                        unsupported()
                    visit(child)
            else:
                unsupported()

        visit(tree.body)
        return
    if id(tp) in seen:
        return
    seen[id(tp)] = tp
    if isinstance(tp, type):
        _ordinary_attribute_access(tp)
    if isinstance(tp, typing.NewType):
        _declarative(tp.__supertype__, seen, namespace)
        return
    if isinstance(tp, typing.TypeAliasType):
        module = sys.modules.get(tp.__module__ or "")
        _declarative(
            tp.__value__, seen, _module_namespace(module) if module is not None else namespace
        )
        return
    if isinstance(tp, typing.TypeVar):
        _declarative(tp.__bound__, seen, namespace)
        for child in tp.__constraints__:
            _declarative(child, seen, namespace)
        return
    origin = typing.get_origin(tp)
    if origin is typing.Literal:
        return
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        _declarative(args[0], seen, namespace)
        return
    if origin is not None:
        _declarative(origin, seen, namespace)
        for child in args:
            _declarative(child, seen, namespace)
    if not isinstance(tp, type):
        return
    if not _model(tp):
        return
    for base in tp.__mro__:
        module = sys.modules.get(base.__module__)
        # Match msgspec's annotation evaluator: module bindings take precedence
        # over class locals (including type parameters) when names collide.
        scope = dict(vars(base))
        scope.update({p.__name__: p for p in getattr(base, "__type_params__", ())})
        scope.update(_module_namespace(module))
        # TypedDict/NamedTuple expose annotations through descriptors on Python 3.14.
        for annotation in getattr(base, "__annotations__", {}).values():
            _declarative(annotation, seen, scope)


def _schema(tp: Any, prefix: str) -> tuple[dict[str, Any], dict[str, Any]]:
    seen: dict[int, Any] = {}
    _declarative(tp, seen)
    try:
        schemas, components = msgspec.json.schema_components(
            [tp], ref_template="#/components/schemas/{name}"
        )
        root = schemas[0]
        _remember_models(seen)
    except _ApplicationCompilationDuringRegistration:
        raise
    except Exception as exc:
        raise TypeError(f"unsupported or ambiguous OpenAPI schema for {tp!r}: {exc}") from exc
    _finite(root)
    _finite(components)
    names: dict[str, str] = {}
    for name in components:
        if not _COMPONENT.fullmatch(name):
            raise TypeError(f"invalid OpenAPI schema component name: {name!r}")
        names[name] = f"{prefix}_{name}"

    return _rewrite_schema(root, names), {
        names[name]: _rewrite_schema(value, names) for name, value in components.items()
    }


def _rewrite_schema(value: Any, names: dict[str, str]) -> Any:
    """Rewrite only schema positions; property names and default/example data are opaque."""
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "$ref":
            prefix = "#/components/schemas/"
            if not isinstance(item, str) or not item.startswith(prefix):
                raise TypeError(f"unsupported external OpenAPI schema reference: {item!r}")
            name = item[len(prefix) :]
            if name not in names:
                raise TypeError(f"unresolved OpenAPI schema reference: {item}")
            result[key] = prefix + names[name]
        elif key in {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}:
            result[key] = {name: _rewrite_schema(child, names) for name, child in item.items()}
        elif key in {"allOf", "anyOf", "oneOf", "prefixItems"}:
            result[key] = [_rewrite_schema(child, names) for child in item]
        elif key in {
            "items",
            "additionalProperties",
            "unevaluatedProperties",
            "contains",
            "propertyNames",
            "not",
            "if",
            "then",
            "else",
            "contentSchema",
            "unevaluatedItems",
            "additionalItems",
        }:
            result[key] = _rewrite_schema(item, names)
        else:
            result[key] = item
    return result


class Registry:
    def __init__(self) -> None:
        self.operations: list[bytes] = []

    def capture(self, route: Any) -> bytes:
        path = route.path
        segments = [] if path == "/" else path[1:].split("/")
        if any(
            ("{" in s or "}" in s) and not (s.startswith("{") and s.endswith("}")) for s in segments
        ):
            raise TypeError("OpenAPI paths require whole-segment path parameters")
        parameters = []
        ints = {name for _, name in route.int_captures}
        for name in route.path_names:
            parameters.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer" if name in ints else "string"},
                }
            )
        for binding in route.input_bindings:
            if binding.source == "header" and binding.name.lower() in {
                "accept",
                "content-type",
                "authorization",
            }:
                raise TypeError(f"OpenAPI cannot represent the {binding.name!r} header parameter")
            schema = {
                str: {"type": "string"},
                int: {"type": "integer"},
                float: {"type": "number"},
                bool: {"type": "boolean"},
            }[binding.annotation].copy()
            param = {
                "name": binding.name,
                "in": binding.source,
                "required": binding.default is _MISSING,
                "schema": schema,
            }
            if binding.default is not _MISSING:
                param["schema"]["default"] = binding.default
            parameters.append(param)
        operation: dict[str, Any] = {"responses": {}}
        if route.summary:
            operation["summary"] = route.summary
        if parameters:
            operation["parameters"] = parameters
        components: dict[str, Any] = {}
        if route.body_type is not None:
            schema, comps = _schema(route.body_type, "body")
            components.update(comps)
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": schema}},
            }
        response_schema = None
        if route.resp_type is not None:
            response_schema, comps = _schema(route.resp_type, "response")
            components.update(comps)
        content = None
        if response_schema is not None:
            content = {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            response_schema,
                            {
                                "type": "object",
                                "properties": {"detail": {}},
                                "required": ["detail"],
                                "additionalProperties": False,
                            },
                        ]
                    }
                }
            }
        operation["responses"]["default"] = {"description": "Application response"}
        if content:
            operation["responses"]["default"]["content"] = content
        for status, desc in ((204, "No Content"), (205, "Reset Content"), (304, "Not Modified")):
            operation["responses"][str(status)] = {"description": desc}
        for status in (400, 404, 405, 422, 500, 503):
            operation["responses"][str(status)] = {"description": "Framework or application error"}
            if content:
                operation["responses"][str(status)]["content"] = content
        shape = tuple("{}" if s.startswith("{") and s.endswith("}") else s for s in segments)
        for snapshot in self.operations:
            existing = msgspec.json.decode(snapshot)
            other = existing["path"]
            other_shape = tuple(
                "{}" if s.startswith("{") and s.endswith("}") else s
                for s in ([] if other == "/" else other[1:].split("/"))
            )
            if other_shape == shape and other != path:
                raise TypeError("ambiguous OpenAPI templated paths")
        record = {
            "path": path,
            "method": route.method.lower(),
            "operation": operation,
            "components": components,
        }
        _finite(record)
        return msgspec.json.encode(record)

    def document(self, title: str, version: str) -> dict[str, Any]:
        paths: dict[str, Any] = {}
        components: dict[str, Any] = {}
        seen: dict[tuple[str, ...], str] = {}
        for index, snapshot in enumerate(self.operations):
            record = msgspec.json.decode(snapshot)
            names = {name: f"e{index}_{name}" for name in record["components"]}
            operation = record["operation"]
            for parameter in operation.get("parameters", []):
                parameter["schema"] = _rewrite_schema(parameter["schema"], names)
            contents = [operation.get("requestBody", {}).get("content", {})]
            contents.extend(
                response.get("content", {}) for response in operation["responses"].values()
            )
            for content in contents:
                for media in content.values():
                    media["schema"] = _rewrite_schema(media["schema"], names)
            p = record["path"]
            shape = tuple(
                "{}" if x.startswith("{") and x.endswith("}") else x
                for x in ([] if p == "/" else p[1:].split("/"))
            )
            if shape in seen and seen[shape] != p:
                raise TypeError("ambiguous OpenAPI templated paths")
            if p not in paths:
                paths[p] = {}
            paths[p][record["method"]] = operation
            components.update(
                {
                    names[name]: _rewrite_schema(schema, names)
                    for name, schema in record["components"].items()
                }
            )
            seen[shape] = p
        result = {"openapi": "3.1.0", "info": {"title": title, "version": version}, "paths": paths}
        if components:
            result["components"] = {"schemas": components}
        return result
