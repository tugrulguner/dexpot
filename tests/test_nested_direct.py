from typing import Any, cast

import msgspec

from dexpot._nested_response import compile_direct


class Leaf(msgspec.Struct):
    value: int


class Root(msgspec.Struct):
    name: str
    rows: list[Leaf]


def test_nested_required_list_uses_direct_projection_without_fallback():
    def raising(_):
        raise AssertionError("fallback called")

    factory, active = compile_direct(Root, raising)
    assert active and factory is not None
    prepare = factory()
    assert prepare(Root("ok", [Leaf(3)])) == {"name": "ok", "rows": [{"value": 3}]}


def test_root_list_of_nested_structs_uses_direct_projection():
    def raising(_):
        raise AssertionError("fallback called")

    factory, active = compile_direct(list[Root], raising)
    assert active and factory is not None
    assert factory()([Root("ok", [Leaf(3)])]) == [{"name": "ok", "rows": [{"value": 3}]}]


def test_nested_mismatch_falls_back_once_with_the_original_root():
    seen = []
    marker = object()

    def fallback(value):
        seen.append(value)
        return marker

    value = [Root("ok", [Leaf(cast(Any, "bad"))])]
    factory, active = compile_direct(list[Root], fallback)
    assert active and factory is not None
    assert factory()(value) is marker
    assert len(seen) == 1 and seen[0] is value


def test_all_generated_helpers_have_worker_private_globals():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import FunctionType

    factory, active = compile_direct(list[Root], lambda _: None)
    assert active and factory is not None
    barrier = threading.Barrier(2)

    def bind(_):
        fn = factory()
        barrier.wait()
        assert fn([Root("ok", [Leaf(3)])]) == [{"name": "ok", "rows": [{"value": 3}]}]
        return fn

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(bind, range(2))
    assert first.__globals__ is not second.__globals__
    assert first.__globals__["_guards"] is not second.__globals__["_guards"]
    for left, right in zip(
        first.__globals__["_guards"], second.__globals__["_guards"], strict=True
    ):
        assert left is not right and left[0] is not right[0]
    for fn in (first, second):
        for value in fn.__globals__.values():
            if (
                isinstance(value, FunctionType)
                and value.__code__.co_filename == "<nested-direct-preparation>"
            ):
                assert value.__globals__ is fn.__globals__


def test_class_mutation_after_guards_cannot_invoke_a_replacement_descriptor():
    called = []
    factory, active = compile_direct(
        list[Leaf], lambda value: (_ for _ in ()).throw(AssertionError("fallback"))
    )
    assert active and factory is not None
    prepare = factory()
    guards = prepare.__globals__["_guards"]
    original = Leaf.value

    def replacement(self):
        called.append(self)
        return 9

    def mutate_after_guard():
        yield from guards
        cast(Any, Leaf).value = property(replacement)

    prepare.__globals__["_guards"] = mutate_after_guard()
    try:
        assert prepare([Leaf(3)]) == [{"value": 3}]
        assert called == []
    finally:
        cast(Any, Leaf).value = original


def test_flat_root_remains_with_its_incumbent():
    factory, active = compile_direct(Leaf, lambda value: value)
    assert factory is None and not active


def test_missing_frozen_child_descriptor_keeps_the_incumbent():
    schema = list[Leaf]
    infos = {schema: msgspec.inspect.type_info(schema)}
    factory, active = compile_direct(schema, lambda value: value, infos=infos)
    assert factory is None and not active
