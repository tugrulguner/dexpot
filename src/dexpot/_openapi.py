"""Registration-time OpenAPI snapshots and detached document generation."""

from __future__ import annotations

import ast
import math
import re
import sys
import typing
from dataclasses import is_dataclass
from types import ModuleType
from typing import Any

import msgspec

from ._inputs import _MISSING
from ._plans import _ApplicationCompilationDuringRegistration

_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("non-finite floats cannot be represented in OpenAPI")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def _declarative(tp: Any, seen: set[Any], namespace: dict[str, Any] | None = None) -> None:
    """Reject calls in type-position forward references, not Literal/metadata strings."""
    namespace = namespace or {}
    if isinstance(tp, typing.ForwardRef):
        module = sys.modules.get(tp.__forward_module__ or "")
        if module is not None:
            namespace = vars(module)
        tp = tp.__forward_arg__
    if isinstance(tp, str):
        tree = ast.parse(tp, mode="eval")
        if any(isinstance(node, ast.Call) for node in ast.walk(tree)):
            raise TypeError(
                "OpenAPI requires declarative schema annotations; construct constrained aliases eagerly"
            )

        def lookup(node: ast.AST) -> Any:
            if isinstance(node, ast.Name):
                return namespace.get(node.id)
            if isinstance(node, ast.Attribute):
                owner = lookup(node.value)
                if isinstance(owner, (ModuleType, type)):
                    return vars(owner).get(node.attr)
            return None

        def visit(node: ast.AST) -> None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                _declarative(node.value, seen, namespace)
            elif isinstance(node, ast.Subscript):
                root = lookup(node.value)
                if root is typing.Literal:
                    return
                _declarative(root, seen, namespace)
                if root is typing.Annotated and isinstance(node.slice, ast.Tuple):
                    visit(node.slice.elts[0])
                else:
                    visit(node.slice)
            elif isinstance(node, (ast.Name, ast.Attribute)):
                _declarative(lookup(node), seen, namespace)
            else:
                for child in ast.iter_child_nodes(node):
                    visit(child)

        visit(tree.body)
        return
    if id(tp) in seen:
        return
    seen.add(id(tp))
    if isinstance(tp, typing.NewType):
        _declarative(tp.__supertype__, seen, namespace)
        return
    if isinstance(tp, typing.TypeAliasType):
        module = sys.modules.get(tp.__module__ or "")
        _declarative(tp.__value__, seen, vars(module) if module is not None else namespace)
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
    if not (
        issubclass(tp, msgspec.Struct)
        or is_dataclass(tp)
        or typing.is_typeddict(tp)
        or (issubclass(tp, tuple) and hasattr(tp, "_fields"))
    ):
        return
    for base in tp.__mro__:
        module = sys.modules.get(base.__module__)
        scope = {**(vars(module) if module is not None else {}), **vars(base), base.__name__: base}
        # TypedDict/NamedTuple expose annotations through descriptors on Python 3.14.
        for annotation in getattr(base, "__annotations__", {}).values():
            _declarative(annotation, seen, scope)


def _schema(tp: Any, prefix: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _declarative(tp, set())
    try:
        schemas, components = msgspec.json.schema_components(
            [tp], ref_template="#/components/schemas/{name}"
        )
        root = schemas[0]
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
