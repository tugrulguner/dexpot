import gc
import importlib.util
import sys
import threading
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict, cast
from uuid import UUID

import msgspec
import pytest

import dexpot._response as candidate
from dexpot._plans import _checked_fallback

reference_path = Path(__file__).resolve().parents[1] / "src/dexpot/_response_legacy.py"
spec = importlib.util.spec_from_file_location("dexpot._audit_reference", reference_path)
assert spec is not None and spec.loader is not None
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class Item(msgspec.Struct):
    value: int


class Private(Item):
    secret: str = "private"


class Tree(msgspec.Struct):
    items: list[Item]
    child: "Tree | None" = None


class Defaults(msgspec.Struct, omit_defaults=True):
    value: int = 3
    items: list[Item] = msgspec.field(default_factory=list)


class Rich(msgspec.Struct):
    moment: datetime
    price: Decimal
    identifier: UUID


class Colour(Enum):
    RED = "red"


class DictRecord(TypedDict):
    value: int


@dataclass
class Record:
    value: int


class A(msgspec.Struct, tag=True):
    value: int


class B(msgspec.Struct, tag=True):
    name: str


class BadDefault(msgspec.Struct):
    value: int = cast(Any, "bad")


cases = [
    (Item, Item(3)),
    (Item, Item(cast(Any, "bad"))),
    (Item, Private(3)),
    (Item, {"value": 3, "secret": "discard"}),
    (Item, {}),
    (Tree, Tree([Item(1), Private(2)])),
    (Tree, Tree([Item(cast(Any, "bad"))])),
    (Tree, {"items": [{"value": 1}], "child": {"items": []}}),
    (Defaults, {}),
    (Defaults, Defaults()),
    (Defaults, {"value": "bad"}),
    (set[int], {1, 2}),
    (set[int], [1, 1, 2]),
    (set[int], ["bad"]),
    (frozenset[int], frozenset({1, 2})),
    (tuple[int, str], (1, "ok")),
    (tuple[int, str], (1,)),
    (dict[str, int], {"ok": 3}),
    (dict[str, int], {"ok": "bad"}),
    (Rich, Rich(datetime(2026, 1, 1, tzinfo=UTC), Decimal("3.2"), UUID(int=1))),
    (Colour, Colour.RED),
    (Colour, "red"),
    (Colour, "blue"),
    (Literal["a", "b"], "a"),
    (Literal["a", "b"], "c"),
    (DictRecord, {"value": 1}),
    (DictRecord, {"value": "bad"}),
    (Record, Record(2)),
    (Record, Record(cast(Any, "bad"))),
    (A | B, A(1)),
    (A | B, B("ok")),
    (A | B, {"type": "A", "value": "bad"}),
    (Annotated[int, msgspec.Meta(ge=2)], 3),
    (Annotated[int, msgspec.Meta(ge=2)], 1),
    (float, float("nan")),
    (float, float("inf")),
    (float, 2.5),
    (Any, {"nested": [1, "ok"]}),
    (bytes, b"hello"),
]
cycle = []
cycle.append(cycle)
cases.append((Any, cycle))


@pytest.mark.parametrize("schema,value", cases)
def test_differential_wire_acceptance(schema, value):
    functions = [
        reference.compile_preparer(schema, _checked_fallback),
        candidate.compile_binding(schema, _checked_fallback).bind(),
        candidate.compile_preparer(schema, _checked_fallback),
    ]
    outcomes = []
    for prepare in functions:
        try:
            outcomes.append(("accepted", msgspec.json.encode(prepare(value))))
        except (TypeError, ValueError, RecursionError, msgspec.ValidationError):
            outcomes.append(("rejected",))
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_invalid_static_default_registration_parity():
    for compile in (
        reference.compile_preparer,
        candidate.compile_preparer,
        candidate.compile_binding,
    ):
        with pytest.raises((ValueError, TypeError)):
            compile(BadDefault, _checked_fallback)


@pytest.mark.skipif(getattr(sys, "_is_gil_enabled", lambda: True)(), reason="FT graph lifetime")
def test_thread_local_graphs_collect_after_thread_churn(monkeypatch):
    references = []
    errors = []
    lock = threading.Lock()
    bind = candidate.PreparationBinding.bind

    def observe(self):
        graph = bind(self)
        with lock:
            references.append(weakref.ref(graph))
        return graph

    monkeypatch.setattr(candidate.PreparationBinding, "bind", observe)
    prepare = candidate.compile_preparer(Tree, _checked_fallback)

    def run():
        try:
            for _ in range(3):
                assert prepare(Tree([Item(1)])) == {"items": [{"value": 1}], "child": None}
        except BaseException as exc:
            with lock:
                errors.append(repr(exc))

    for _ in range(4):
        threads = [threading.Thread(target=run) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        del threads
    gc.collect()
    gc.collect()
    assert not errors
    assert len(references) == 96
    assert sum(ref() is not None for ref in references) == 0


def test_shared_native_fallback_concurrent_wire_parity():
    schema = set[int]
    factory = candidate.compile_binding(schema, _checked_fallback)
    bound = [factory.bind() for _ in range(8)]
    expected = msgspec.json.encode(reference.compile_preparer(schema, _checked_fallback)({1, 2}))
    errors = []

    def run(prepare):
        try:
            for _ in range(1000):
                assert msgspec.json.encode(prepare({1, 2})) == expected
        except BaseException as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=run, args=(prepare,)) for prepare in bound]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
