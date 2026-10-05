"""Class signatures must resolve annotations in their effective constructor scope."""

from __future__ import annotations

import dis
import functools
import inspect
import socket
from typing import Any

import msgspec
import pytest

from dexpot import Dex, Request


def _namespace(source: str, **bindings: Any) -> dict[str, Any]:
    namespace = dict(bindings)
    exec(compile(source, "<class-handler-test>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "source",
    [
        "class Handler:\n def __init__(self, item_id: Alias): self.item_id = item_id\n",
        "class Handler:\n"
        " def __new__(cls, item_id: Alias):\n"
        "  obj = object.__new__(cls); obj.item_id = item_id; return obj\n",
        "class Meta(type):\n"
        " def __call__(cls, item_id: Alias): return {'item_id': item_id}\n"
        "class Handler(metaclass=Meta):\n"
        " def __init__(self, unrelated: str): pass\n",
        "class Base:\n"
        " def __init__(self, item_id: Alias): self.item_id = item_id\n"
        "class Handler(Base): pass\n",
        "class Base:\n"
        " def __new__(cls, item_id: Alias): return object.__new__(cls)\n"
        "class Handler(Base):\n"
        " def __init__(self, item_id: Alias): self.item_id = item_id\n",
    ],
    ids=["init", "new", "metaclass", "inherited-init", "derived-init"],
)
def test_class_signature_sources_compile_direct_invokers(source: str) -> None:
    handler = _namespace(source, Alias=int)["Handler"]
    app = Dex()
    app.get("/{item_id}")(handler)
    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ((0, "item_id"),)
    result = endpoint.invoke([7], None)
    assert (result["item_id"] if isinstance(result, dict) else result.item_id) == 7
    instructions = {item.opname for item in dis.get_instructions(endpoint.invoke)}
    assert not instructions & {"BUILD_LIST", "BUILD_MAP", "CALL_FUNCTION_EX", "LOAD_GLOBAL"}


@pytest.mark.parametrize("derived_method", ["__init__", "__new__"])
def test_constructor_owner_obeys_mro_before_new_init_priority(derived_method: str) -> None:
    base_method = "__new__" if derived_method == "__init__" else "__init__"
    base = _namespace(
        f"class Base:\n def {base_method}(self, item_id: Alias):\n  return object.__new__(self)\n"
        if base_method == "__new__"
        else "class Base:\n def __init__(self, item_id: Alias): pass\n",
        Alias=str,
    )["Base"]
    handler = _namespace(
        f"class Handler(Base):\n def {derived_method}(self, item_id: Alias):\n"
        "  return object.__new__(self)\n"
        if derived_method == "__new__"
        else "class Handler(Base):\n def __init__(self, item_id: Alias): pass\n",
        Base=base,
        Alias=int,
    )["Handler"]
    app = Dex()
    app.get("/{item_id}")(handler)
    assert app._compile().endpoints[0].int_captures == ((0, "item_id"),)


@pytest.mark.parametrize("kind", ["coroutine", "async-generator", "wrapped-coroutine"])
def test_partialmethod_constructor_rejects_async_targets_atomically(kind: str) -> None:
    async def coroutine(self, prefix):
        return None

    async def generator(self, prefix):
        yield None

    @functools.wraps(coroutine)
    def wrapped(self, prefix):
        return coroutine(self, prefix)

    target = {"coroutine": coroutine, "async-generator": generator, "wrapped-coroutine": wrapped}[
        kind
    ]
    handler = type("Handler", (), {"__init__": functools.partialmethod(target, "prefix")})
    app = Dex()
    with pytest.raises(TypeError, match="asynchronous handlers are not supported"):
        app.get("/")(handler)
    assert not app._endpoints and not app._literal and not app._parametric


def test_partialmethod_constructor_uses_original_annotation_namespace() -> None:
    handler = _namespace(
        "class Handler:\n"
        " def init(self, prefix, item_id: Alias, *, request: Context):\n"
        "  self.item_id = item_id; self.method = request.method\n"
        " __init__ = functools.partialmethod(init, 'prefix')\n",
        functools=functools,
        Alias=int,
        Context=Request,
    )["Handler"]
    app = Dex()
    app.get("/{item_id}")(handler)
    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ((0, "item_id"),)
    assert endpoint.needs_request
    result = endpoint.invoke([7], None, Request("GET", "/7", {}, "", {}))
    assert result.item_id == 7 and result.method == "GET"
    instructions = {item.opname for item in dis.get_instructions(endpoint.invoke)}
    assert not instructions & {"BUILD_LIST", "BUILD_MAP", "CALL_FUNCTION_EX", "LOAD_GLOBAL"}


def test_partialmethod_constructor_preserves_explicit_wrapper_signature_scope() -> None:
    original = _namespace(
        "def init(self, prefix, item_id: Alias): self.item_id = item_id", Alias=str
    )["init"]
    wrapper = _namespace(
        "@functools.wraps(original)\n"
        "def wrapped(self, prefix, item_id): return original(self, prefix, item_id)\n",
        functools=functools,
        original=original,
        Alias=int,
    )["wrapped"]
    wrapper.__signature__ = inspect.Signature(
        [
            inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("prefix", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter(
                "item_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Alias"
            ),
        ]
    )
    handler = type("Handler", (), {"__init__": functools.partialmethod(wrapper, "prefix")})
    app = Dex()
    app.get("/{item_id}")(handler)
    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ((0, "item_id"),)
    assert endpoint.invoke([7], None).item_id == 7


def test_new_precedes_init_on_the_same_class() -> None:
    new = _namespace("def new(cls, item_id: Alias): return object.__new__(cls)", Alias=int)["new"]
    init = _namespace("def init(self, item_id: Alias): pass", Alias=str)["init"]
    handler = type("Handler", (), {"__new__": new, "__init__": init})
    app = Dex()
    app.get("/{item_id}")(handler)
    assert app._compile().endpoints[0].int_captures == ((0, "item_id"),)


def test_constructor_wrappers_and_partials_preserve_original_globals() -> None:
    original = _namespace(
        "def init(self, kind, item_id: Alias): self.item_id = item_id", Alias=int
    )["init"]

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        return original(*args, **kwargs)

    handler: Any = type("Handler", (), {"__init__": wrapped})
    app = Dex()
    app.get("/{item_id}")(functools.partial(handler, "partial"))
    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ((0, "item_id"),)
    assert endpoint.invoke([7], None).item_id == 7


def test_class_explicit_signature_does_not_guess_a_constructor_namespace() -> None:
    handler = _namespace("class Handler:\n def __init__(self, item_id: Alias): pass\n", Alias=str)[
        "Handler"
    ]
    handler.__signature__ = inspect.Signature(
        [inspect.Parameter("item_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Alias")]
    )
    app = Dex()
    with pytest.raises(TypeError, match="annotation_locals"):
        app.get("/{item_id}")(handler)
    assert not app._endpoints and not app._literal and not app._parametric
    app.get("/{item_id}", annotation_locals={"Alias": int})(handler)
    assert app._compile().endpoints[0].int_captures == ((0, "item_id"),)


def test_constructor_closure_overrides_explicit_namespace() -> None:
    def build():
        Alias: Any = int

        class Handler:
            def __init__(self, item_id: Alias):  # type: ignore[valid-type]
                self.item_id = Alias(item_id)

        return Handler

    app = Dex()
    app.get("/{item_id}", annotation_locals={"Alias": str})(build())
    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ((0, "item_id"),)
    assert endpoint.invoke([7], None).item_id == 7


@pytest.mark.parametrize("use_partialmethod", [False, True])
def test_class_metaclass_handler_converts_and_injects_context_over_real_http(
    use_partialmethod: bool,
) -> None:
    source = (
        "class Meta(type):\n"
        " def call(cls, prefix, item_id: Alias, *, request: Context):\n"
        "  return {'item_id': item_id, 'method': request.method}\n"
        " __call__ = functools.partialmethod(call, 'prefix')\n"
        "class Handler(metaclass=Meta): pass\n"
        if use_partialmethod
        else "class Meta(type):\n"
        " def __call__(cls, item_id: Alias, *, request: Context):\n"
        "  return {'item_id': item_id, 'method': request.method}\n"
        "class Handler(metaclass=Meta): pass\n"
    )
    handler = _namespace(
        source,
        functools=functools,
        Alias=int,
        Context=Request,
    )["Handler"]
    app = Dex()
    app.get("/{item_id}")(handler)
    app._compile()
    for path, status, expected in [
        ("/7", 200, {"item_id": 7, "method": "GET"}),
        ("/invalid", 422, {"detail": "invalid int for item_id"}),
    ]:
        client, server = socket.socketpair()
        try:
            client.settimeout(2)
            client.sendall(
                f"GET {path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode()
            )
            keep_alive, remaining = app._process(server, b"")
            response = client.recv(4096)
        finally:
            client.close()
            server.close()
        assert not keep_alive and not remaining
        assert response.startswith(f"HTTP/1.1 {status}".encode())
        assert msgspec.json.decode(response.split(b"\r\n\r\n", 1)[1]) == expected
