import sys
import threading
from typing import Any, cast

import msgspec
import pytest

import dexpot._response as response
from dexpot._plans import _checked_fallback


class Nested(msgspec.Struct):
    values: list[int]


@pytest.mark.skipif(not getattr(sys, "_is_gil_enabled", lambda: True)(), reason="real GIL path")
def test_gil_returns_canonical_without_serving_thread_bind(monkeypatch):
    factories = []
    compile_binding = response.compile_binding

    def capture(schema, fallback):
        factory = compile_binding(schema, fallback)
        factories.append(factory)
        return factory

    monkeypatch.setattr(response, "compile_binding", capture)
    prepare = response.compile_preparer(Nested, _checked_fallback)
    assert prepare is factories[0].canonical
    monkeypatch.setattr(
        response.PreparationBinding,
        "bind",
        lambda self: pytest.fail("GIL route bound a thread graph"),
    )
    assert prepare(Nested([1])) == {"values": [1]}
    with pytest.raises((ValueError, TypeError)):
        prepare(Nested([cast(Any, ["bad"])]))


@pytest.mark.skipif(getattr(sys, "_is_gil_enabled", lambda: True)(), reason="real FT path")
def test_ft_still_binds_one_distinct_graph_per_serving_thread(monkeypatch):
    graphs = []
    errors = []
    lock = threading.Lock()
    original_bind = response.PreparationBinding.bind

    def record(self):
        graph = original_bind(self)
        with lock:
            graphs.append(graph)
        return graph

    monkeypatch.setattr(response.PreparationBinding, "bind", record)
    prepare = response.compile_preparer(Nested, _checked_fallback)

    def run():
        try:
            for _ in range(10):
                assert prepare(Nested([1])) == {"values": [1]}
        except BaseException as exc:
            with lock:
                errors.append(repr(exc))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(graphs) == len({id(graph) for graph in graphs}) == 8


def test_legacy_interpreter_without_gil_query_uses_canonical(monkeypatch):
    factories = []
    compile_binding = response.compile_binding

    def capture(schema, fallback):
        factory = compile_binding(schema, fallback)
        factories.append(factory)
        return factory

    monkeypatch.setattr(response, "compile_binding", capture)
    monkeypatch.delattr(sys, "_is_gil_enabled", raising=False)
    prepare = response.compile_preparer(Nested, _checked_fallback)
    assert prepare is factories[0].canonical
    assert prepare(Nested([1])) == {"values": [1]}


def test_gil_canonical_graph_lifetime_matches_route_lifetime():
    import gc
    import weakref

    if not getattr(sys, "_is_gil_enabled", lambda: True)():
        pytest.skip("real GIL graph lifecycle")
    prepare = response.compile_preparer(Nested, _checked_fallback)
    reference = weakref.ref(prepare)
    errors = []

    def run(preparer):
        try:
            assert preparer(Nested([1])) == {"values": [1]}
        except BaseException as exc:
            errors.append(repr(exc))

    for _ in range(4):
        threads = [threading.Thread(target=run, args=(prepare,)) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        del threads
    gc.collect()
    assert not errors and reference() is prepare
    del prepare
    gc.collect()
    assert reference() is None


def test_runtime_selected_preparer_defers_factory_and_uses_snapshot(monkeypatch):
    calls = []

    def factory():
        calls.append(True)
        return [1]

    class Output(msgspec.Struct):
        values: list[int] = msgspec.field(default_factory=factory)

    prepare = response.compile_preparer(Output, _checked_fallback)
    assert calls == []
    monkeypatch.setattr(response, "type_info", lambda *args: pytest.fail("runtime reinspection"))
    assert prepare({}) == {"values": [1]}
    assert calls == [True]
