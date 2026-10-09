import msgspec

import dexpot._response as response
from dexpot._plans import _checked_fallback


class Node(msgspec.Struct):
    value: int
    child: "Node | None" = None


class Output(msgspec.Struct):
    value: int


def test_binding_uses_registration_snapshot(monkeypatch):
    factory = response.compile_binding(Output, _checked_fallback)

    def forbidden(*args, **kwargs):
        raise AssertionError("schema inspected after registration")

    monkeypatch.setattr(response, "type_info", forbidden)
    monkeypatch.setattr(msgspec.structs, "fields", forbidden)
    a, b = factory.bind(), factory.bind()
    assert a is not b
    assert a(Output(3)) == b(Output(3)) == {"value": 3}
    try:
        a(Output("bad"))  # pyright: ignore[reportArgumentType]
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError("strict validation lost")


def test_factory_identity_and_no_registration_or_binding_execution():
    calls = []

    def factory():
        calls.append(True)
        return [1]

    class WithFactory(msgspec.Struct):
        values: list[int] = msgspec.field(default_factory=factory)

    plan = response.compile_binding(WithFactory, _checked_fallback)
    a, b = plan.bind(), plan.bind()
    assert calls == []
    assert a({}) == {"values": [1]}
    assert b({}) == {"values": [1]}
    assert len(calls) == 2
    for info in plan.infos.values():
        if isinstance(info, msgspec.inspect.StructType):
            assert info.fields[0].default_factory is factory


def test_recursive_snapshot_and_distinct_owned_cells(monkeypatch):
    plan = response.compile_binding(Node, _checked_fallback)
    monkeypatch.setattr(
        response, "type_info", lambda _: (_ for _ in ()).throw(AssertionError("reinspection"))
    )
    a, b = plan.bind(), plan.bind()
    expected = {"value": 1, "child": {"value": 2, "child": None}}
    assert a(Node(1, Node(2))) == b(Node(1, Node(2))) == expected
    assert not {id(c) for c in (a.__closure__ or ())} & {id(c) for c in (b.__closure__ or ())}


def test_record_hints_are_snapshotted(monkeypatch):
    from dataclasses import make_dataclass

    Record = make_dataclass("Record", [("value", int)])
    plan = response.compile_binding(Record, _checked_fallback)
    Record.__annotations__["value"] = str
    monkeypatch.setattr(
        response,
        "get_type_hints",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("reinspection")),
    )
    assert plan.bind()(Record(3)) == {"value": 3}
