"""Single preparation invariants and checked-response edge cases."""

from typing import Any, cast

import msgspec
import pytest

from dexpot import Dex
from test_response_policy import Container, Private, Public, request


def test_checked_graph_has_one_preparation_without_container_normalization(monkeypatch):
    calls = []
    original = msgspec.to_builtins

    def observe(value, *args, **kwargs):
        if isinstance(value, (msgspec.Struct, dict, list, tuple)):
            calls.append(type(value))
        return original(value, *args, **kwargs)

    app = Dex()
    app.get("/value", response=Container)(lambda: Container([Private("ok", "hidden")]))
    monkeypatch.setattr(msgspec, "to_builtins", observe)
    assert request(app)[::2] == (200, b'{"entries":[{"name":"ok"}]}')
    assert calls == [], "checked graphs must be prepared directly, without normalization passes"


@pytest.mark.parametrize(
    "schema,value",
    [
        (Any, {"x": [1, "ok"]}),
        (dict, {"x": [1, "ok"]}),
        (dict[str, list[int]], {"x": [1, 2]}),
        (list[int] | None, [1, 2]),
    ],
)
def test_dynamic_containers_are_prepared_without_normalization(monkeypatch, schema, value):
    original = msgspec.to_builtins
    calls = []

    def observe(item, *args, **kwargs):
        if isinstance(item, (dict, list, tuple, msgspec.Struct)):
            calls.append(type(item))
        return original(item, *args, **kwargs)

    app = Dex()
    app.get("/value", response=schema)(lambda: value)
    monkeypatch.setattr(msgspec, "to_builtins", observe)
    assert request(app)[0] == 200
    assert calls == []


def test_tagged_union_selects_before_evaluating_defaults():
    calls = []

    class First(msgspec.Struct, tag=True):
        name: str = msgspec.field(default_factory=lambda: calls.append(1) or "wrong")

    class Second(msgspec.Struct, tag=True):
        name: str

    app = Dex()
    app.get("/value", response=First | Second)(lambda: Second("ok"))
    assert request(app)[::2] == (200, b'{"type":"Second","name":"ok"}')
    assert calls == []


def test_any_preserves_omitted_defaults():
    class Omitted(msgspec.Struct, omit_defaults=True):
        name: str = "ok"

    app = Dex()
    app.get("/value", response=Any)(lambda: Omitted())
    assert request(app)[::2] == (200, b"{}")


def test_rich_graph_does_not_repeat_container_normalization(monkeypatch):
    from datetime import UTC, datetime
    from uuid import UUID

    calls = []
    original = msgspec.to_builtins

    def observe(value, *args, **kwargs):
        if isinstance(value, (msgspec.Struct, dict, list, tuple)):
            calls.append(type(value))
        return original(value, *args, **kwargs)

    monkeypatch.setattr(msgspec, "to_builtins", observe)

    class Rich(msgspec.Struct):
        date: datetime
        uid: UUID
        blob: bytes

    app = Dex()
    app.get("/value", response=Rich)(
        lambda: Rich(datetime(2026, 1, 1, tzinfo=UTC), UUID(int=0), b"abc")
    )
    assert request(app)[0] == 200
    assert calls == []


def test_nullable_struct_accepts_untagged_mapping():
    app = Dex()
    app.get("/value", response=Public | None)(lambda: {"name": "ok"})
    assert request(app)[::2] == (200, b'{"name":"ok"}')


def test_struct_accepts_dataclass_source():
    from dataclasses import dataclass

    @dataclass
    class Source:
        name: str
        secret: str

    app = Dex()
    app.get("/value", response=Public)(lambda: Source("ok", "hidden"))
    assert request(app)[::2] == (200, b'{"name":"ok"}')


def test_numeric_union_preserves_native_integer_selection():
    app = Dex()
    app.get("/value", response=float | int)(lambda: 1)
    assert request(app)[::2] == (200, b"1")


def test_omitted_nested_and_rich_static_defaults():
    from datetime import UTC, datetime

    class Frozen(msgspec.Struct, frozen=True):
        name: str = "ok"

    class Output(msgspec.Struct, omit_defaults=True):
        child: Frozen = Frozen()
        date: datetime = datetime(2026, 1, 1, tzinfo=UTC)

    app = Dex()
    app.get("/value", response=Output)(lambda: {})
    assert request(app)[::2] == (200, b"{}")


def test_source_omission_precedes_target_default_selection():
    class Source(msgspec.Struct, omit_defaults=True):
        name: str = "source"

    class Target(msgspec.Struct):
        name: str = "target"

    app = Dex()
    app.get("/value", response=Target)(lambda: Source())
    assert request(app)[::2] == (200, b'{"name":"target"}')


@pytest.mark.parametrize("kind", ["dataclass", "tuple", "array"])
def test_additional_schema_graphs_avoid_normalization(monkeypatch, kind):
    from dataclasses import dataclass

    @dataclass
    class Record:
        name: str

    class Array(msgspec.Struct, array_like=True):
        names: list[str]

    schema, value, expected = {
        "dataclass": (Record, {"name": "ok", "secret": "hidden"}, b'{"name":"ok"}'),
        "tuple": (tuple[Public, ...], [Private("ok", "hidden")], b'[{"name":"ok"}]'),
        "array": (Array, [["ok"]], b'[["ok"]]'),
    }[kind]
    original = msgspec.to_builtins
    calls = []

    def observe(item, *args, **kwargs):
        if isinstance(item, (dict, list, tuple, msgspec.Struct)):
            calls.append(type(item))
        return original(item, *args, **kwargs)

    app = Dex()
    app.get("/value", response=schema)(lambda: value)
    monkeypatch.setattr(msgspec, "to_builtins", observe)
    assert request(app)[::2] == (200, expected)
    assert calls == []


def test_rich_graph_is_encoded_only_after_preparation(monkeypatch):
    from datetime import UTC, datetime

    class Rich(msgspec.Struct):
        date: datetime

    app = Dex()
    app.get("/value", response=Rich)(lambda: Rich(datetime(2026, 1, 1, tzinfo=UTC)))
    calls = []
    original = msgspec.json.encode

    def observe(value, *args, **kwargs):
        calls.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(msgspec.json, "encode", observe)
    assert request(app)[::2] == (200, b'{"date":"2026-01-01T00:00:00Z"}')
    assert calls == [], "native Encoder must pack the prepared response once"


@pytest.mark.parametrize("kind", ["array_union", "array_to_list", "struct_to_dict"])
def test_native_source_shapes_remain_accepted(kind):
    class A(msgspec.Struct, tag="a", array_like=True):
        number: int

    class B(msgspec.Struct, tag="b", array_like=True):
        name: str

    schema, value, expected = {
        "array_union": (A | B, ["a", 1], b'["a",1]'),
        "array_to_list": (list, A(1), b'["a",1]'),
        "struct_to_dict": (dict[str, Any], Public("ok"), b'{"name":"ok"}'),
    }[kind]
    app = Dex()
    app.get("/value", response=schema)(lambda: value)
    assert request(app)[::2] == (200, expected)


def test_nested_default_validation_does_not_execute_application_factories():
    calls = []

    class Inner(msgspec.Struct):
        name: str = msgspec.field(default_factory=lambda: calls.append(1) or "ok")

    class Outer(msgspec.Struct):
        child: Inner = cast(Any, msgspec.field(default_factory=dict))

    app = Dex()
    app.get("/value", response=Outer)(lambda: {})
    assert calls == []
    assert request(app)[::2] == (200, b'{"child":{"name":"ok"}}')
    assert calls == [1]


def test_static_dataclass_defaults_fail_registration_atomically():
    from dataclasses import dataclass

    @dataclass
    class Invalid:
        count: int = "invalid"  # type: ignore[assignment]

    app = Dex()
    with pytest.raises(TypeError, match="invalid checked response default"):
        app.get("/value", response=Invalid)(lambda: {})
    assert app._endpoints == []
    assert app._literal == {}


@pytest.mark.parametrize("key", [1, True, None])
def test_struct_unknown_keys_obey_native_object_grammar(key):
    app = Dex()
    app.get("/value", response=Public)(lambda: {"name": "ok", key: "hidden"})
    assert request(app)[0] == 500


def test_invalid_static_any_object_key_fails_registration():
    class Frozen(msgspec.Struct, frozen=True):
        value: Any

    class Output(msgspec.Struct):
        value: Any = Frozen({True: 1})

    app = Dex()
    with pytest.raises(TypeError, match="invalid checked response default"):
        app.get("/value", response=Output)(lambda: {})


def test_recursive_factory_defaults_are_fully_prepared():
    calls = []

    class Inner(msgspec.Struct):
        value: Public = msgspec.field(
            default_factory=lambda: calls.append("inner") or Private("ok", "hidden")
        )

    class Middle(msgspec.Struct):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    app = Dex()
    app.get("/value", response=Outer)(lambda: {})
    assert calls == []
    assert request(app)[::2] == (200, b'{"middle":{"inner":{"value":{"name":"ok"}}}}')
    assert calls == ["inner"]


def test_private_fields_and_default_factories_cannot_hide_request():
    from dexpot import Request

    context = Request("GET", "/", {}, "", {})

    class Hidden(Public):
        secret: Any

    class Inner(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Hidden("ok", context))

    class Outer(msgspec.Struct):
        inner: Inner = cast(Any, msgspec.field(default_factory=dict))

    app = Dex()
    app.get("/value", response=Outer)(lambda: {})
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


def test_shared_references_are_not_treated_as_cycles():
    shared = Private("ok", "hidden")
    app = Dex()
    app.get("/value", response=list[Public])(lambda: [shared, shared])
    assert request(app)[::2] == (200, b'[{"name":"ok"},{"name":"ok"}]')


def test_prepared_graph_is_owned_before_native_encoding():
    app = Dex()
    value = {"items": [{"name": "ok"}]}
    app.get("/value", response=Any)(lambda: value)
    plan = app._literal["GET", "/value"]
    original = plan.resp_encoder

    class ObserveEncoder:
        def encode(self, prepared):
            value["items"][0]["name"] = "changed"
            return original.encode(prepared)

    object.__setattr__(plan, "resp_encoder", ObserveEncoder())
    assert request(app)[::2] == (200, b'{"items":[{"name":"ok"}]}')


def test_non_string_mapping_values_get_recursive_default_preparation():
    class Inner(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Private("ok", "hidden"))

    class Middle(msgspec.Struct):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    app = Dex()
    app.get("/value", response=dict[int, Outer])(lambda: {1: {}})
    assert request(app)[::2] == (200, b'{"1":{"middle":{"inner":{"value":{"name":"ok"}}}}}')


def test_static_defaults_are_checked_below_fallback_containers():
    class Invalid(msgspec.Struct, frozen=True):
        count: int = cast(Any, "invalid")

    app = Dex()
    with pytest.raises(TypeError, match="invalid checked response default"):
        app.get("/value", response=set[Invalid])(lambda: [])


@pytest.mark.parametrize("kind", ["namedtuple", "typeddict"])
def test_record_containers_prepare_recursive_defaults(kind):
    from typing import NamedTuple, TypedDict

    class Inner(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Private("ok", "hidden"))

    class Middle(msgspec.Struct):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    class TupleRecord(NamedTuple):
        outer: Outer

    class DictRecord(TypedDict):
        outer: Outer

    schema, value, expected = (
        (TupleRecord, [{}], b'[{"middle":{"inner":{"value":{"name":"ok"}}}}]')
        if kind == "namedtuple"
        else (DictRecord, {"outer": {}}, b'{"outer":{"middle":{"inner":{"value":{"name":"ok"}}}}}')
    )
    app = Dex()
    app.get("/value", response=schema)(lambda: value)
    assert request(app)[::2] == (200, expected)


def test_namedtuple_rejects_trailing_elements():
    from typing import NamedTuple

    class Record(NamedTuple):
        name: str

    app = Dex()
    app.get("/value", response=Record)(lambda: ["ok", "extra"])
    assert request(app)[0] == 500


def test_set_native_fallback_prepares_recursive_defaults_first():
    class Inner(msgspec.Struct, eq=False):
        value: Public = msgspec.field(default_factory=lambda: Private("ok", "hidden"))

    class Middle(msgspec.Struct, eq=False):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct, eq=False):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    app = Dex()
    app.get("/value", response=set[Outer])(lambda: [{}])
    assert request(app)[::2] == (200, b'[{"middle":{"inner":{"value":{"name":"ok"}}}}]')


def test_generic_dataclass_prepares_recursive_defaults():
    from dataclasses import dataclass
    from typing import Generic, TypeVar

    T = TypeVar("T")

    class Inner(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Private("ok", "hidden"))

    class Middle(msgspec.Struct):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    @dataclass
    class Box(Generic[T]):
        item: T

    app = Dex()
    app.get("/value", response=Box[Outer])(lambda: {"item": {}})
    assert request(app)[::2] == (200, b'{"item":{"middle":{"inner":{"value":{"name":"ok"}}}}}')


def test_checked_response_documentation_describes_preparation_and_fallback():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("README.md", "ROADMAP.md", "CONTRIBUTING.md"):
        content = " ".join((root / name).read_text().split())
        assert "schema-directed preparation" in content
        assert "fallback" in content
    skill = (root / "src/dexpot/templates/skills/dexpot.md").read_text()
    assert "Struct and dataclass defaults" in skill


def test_set_default_validation_defers_nested_application_factories():
    calls = []

    class Inner(msgspec.Struct, eq=False):
        name: str = msgspec.field(default_factory=lambda: calls.append(1) or "ok")

    class Output(msgspec.Struct):
        items: set[Inner] = cast(Any, ({},))

    app = Dex()
    app.get("/value", response=Output)(lambda: {})
    assert calls == []
    assert request(app)[::2] == (200, b'{"items":[{"name":"ok"}]}')
    assert calls == [1]


def test_generic_dataclass_retains_annotated_constraints():
    from dataclasses import dataclass
    from typing import Annotated, Generic, TypeVar

    T = TypeVar("T")

    @dataclass
    class Box(Generic[T]):
        value: Annotated[T, msgspec.Meta(ge=1)]

    app = Dex()
    app.get("/value", response=Box[int])(lambda: {"value": 2})
    app.get("/invalid", response=Box[int])(lambda: {"value": 0})
    assert request(app)[::2] == (200, b'{"value":2}')
    assert request(app, "/invalid")[0] == 500


def test_enum_container_sources_preserve_native_normalization_semantics():
    from enum import Enum

    class Value(Enum):
        OBJECT = {"name": "ok"}  # noqa: RUF012 -- exercise container-valued Enum members
        ARRAY = [{"name": "ok"}]  # noqa: RUF012 -- exercise container-valued Enum members

    for schema, value, expected in (
        (Public, Value.OBJECT, b'{"name":"ok"}'),
        (list[Public], Value.ARRAY, b'[{"name":"ok"}]'),
    ):
        app = Dex()
        app.get("/value", response=schema)(lambda value=value: value)
        assert request(app)[::2] == (200, expected)


def test_tagged_union_accepts_dataclass_source():
    from dataclasses import dataclass

    class A(msgspec.Struct, tag="a"):
        name: str

    class B(msgspec.Struct, tag="b"):
        name: str

    @dataclass
    class Source:
        type: str = "a"
        name: str = "ok"

    app = Dex()
    app.get("/value", response=A | B)(lambda: Source())
    assert request(app)[::2] == (200, b'{"type":"a","name":"ok"}')


@pytest.mark.parametrize("value", [False, 0.0])
def test_source_omission_cannot_hide_malformed_primitive(value):
    class Output(msgspec.Struct, omit_defaults=True):
        count: int = 0

    app = Dex()
    app.get("/value", response=Output)(lambda: Output(value))
    assert request(app)[0] == 500


def test_source_factory_omission_uses_native_container_type():
    class Output(msgspec.Struct, omit_defaults=True):
        values: list[int] = msgspec.field(default_factory=list)

    app = Dex()
    app.get("/value", response=Output)(lambda: Output(cast(Any, "")))
    assert request(app)[0] == 500


def test_omission_does_not_hide_equal_but_malformed_nested_value():
    class Inner(msgspec.Struct, frozen=True):
        count: int = 0

    class Output(msgspec.Struct, omit_defaults=True):
        inner: Inner = Inner()

    app = Dex()
    app.get("/value", response=Output)(lambda: Output(Inner(cast(Any, False))))
    assert request(app)[0] == 500


def test_static_omission_preserves_native_identity_semantics():
    class Inner(msgspec.Struct, frozen=True):
        count: int = 0

    class Output(msgspec.Struct, omit_defaults=True):
        inner: Inner = Inner()
        number: float = 1

    app = Dex()
    app.get("/value", response=Output)(lambda: {})
    app.get("/distinct", response=Output)(lambda: {"inner": Inner(), "number": 1})
    assert request(app)[::2] == (200, b"{}")
    assert request(app, "/distinct")[::2] == (200, b'{"inner":{"count":0},"number":1.0}')


def test_native_string_like_object_keys_are_normalized():
    from enum import Enum

    class Key(Enum):
        NAME = "name"

    app = Dex()
    app.get("/value", response=Public)(lambda: {Key.NAME: "ok"})
    assert request(app)[::2] == (200, b'{"name":"ok"}')


@pytest.mark.parametrize("source", ["struct", "missing"])
def test_unset_record_defaults_remain_omitted(source):
    class Output(msgspec.Struct):
        count: int | msgspec.UnsetType = msgspec.UNSET

    app = Dex()
    app.get("/value", response=Output)(lambda: Output() if source == "struct" else {})
    assert request(app)[::2] == (200, b"{}")


def test_unset_cannot_hide_required_fields_or_skip_static_defaults():
    class Required(msgspec.Struct):
        count: int

    class Defaulted(msgspec.Struct):
        count: int = 3

    app = Dex()
    app.get("/value", response=Required)(lambda: Required(cast(Any, msgspec.UNSET)))
    app.get("/default", response=Defaulted)(lambda: Defaulted(cast(Any, msgspec.UNSET)))
    assert request(app)[0] == 500
    assert request(app, "/default")[::2] == (200, b'{"count":3}')


def test_any_dataclass_omits_unset_fields():
    from dataclasses import dataclass

    @dataclass
    class Output:
        count: int | msgspec.UnsetType = msgspec.UNSET

    app = Dex()
    app.get("/value", response=Any)(lambda: Output())
    assert request(app)[::2] == (200, b"{}")


@pytest.mark.parametrize("shape", ["container", "union"])
def test_schema_metadata_preserves_recursive_preparation(shape):
    from typing import Annotated

    class Inner(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Private("ok", "hidden"))

    class Middle(msgspec.Struct):
        inner: Inner = msgspec.field(default_factory=Inner)

    class Outer(msgspec.Struct):
        middle: Middle = cast(Any, msgspec.field(default_factory=dict))

    record_type: Any = Annotated[Outer, msgspec.Meta(description="Public output")]
    schema, value, expected = (
        (
            Annotated[list[Outer], msgspec.Meta(description="Outputs")],
            [{}],
            b'[{"middle":{"inner":{"value":{"name":"ok"}}}}]',
        )
        if shape == "container"
        else (record_type | None, {}, b'{"middle":{"inner":{"value":{"name":"ok"}}}}')
    )
    app = Dex()
    app.get("/value", response=schema)(lambda: value)
    assert request(app)[::2] == (200, expected)


def test_native_attrs_field_metadata_preserves_projection_and_privacy():
    from types import SimpleNamespace

    from dexpot import Request

    # This is the field-name protocol consumed by msgspec's native attrs encoder.
    # Exercise the real codec without adding an optional attrs dependency.
    class Source:
        __attrs_attrs__ = (SimpleNamespace(name="name"), SimpleNamespace(name="secret"))

        def __init__(self, secret):
            self.name = "ok"
            self.secret = secret

    assert msgspec.to_builtins(Source("hidden")) == {"name": "ok", "secret": "hidden"}
    app = Dex()
    app.get("/value", response=Public)(lambda: Source("hidden"))
    app.get("/private", response=Any)(lambda: Source(Request("GET", "/", {}, "", {})))
    assert request(app)[::2] == (200, b'{"name":"ok"}')
    assert request(app, "/private")[0] == 500


def test_rich_scalar_omission_compares_validated_native_value():
    from enum import Enum

    class Choice(str, Enum):  # noqa: UP042 -- exercise native enum conversion
        YES = "yes"

    class Output(msgspec.Struct, omit_defaults=True):
        choice: Choice = cast(Any, "yes")
        blob: bytes = cast(Any, "")

    app = Dex()
    app.get("/value", response=Output)(lambda: {"choice": "yes", "blob": ""})
    assert request(app)[::2] == (200, b'{"choice":"yes","blob":""}')


def test_any_default_enum_is_not_the_normalized_string():
    from enum import Enum

    class Choice(Enum):
        YES = "yes"

    class Output(msgspec.Struct, omit_defaults=True):
        choice: Any = Choice.YES

    app = Dex()
    app.get("/value", response=Output)(lambda: {"choice": Choice.YES})
    assert request(app)[::2] == (200, b'{"choice":"yes"}')


def test_request_subclass_schema_cannot_enter_exact_record_preparation():
    from dexpot import Request

    class Context(Request, frozen=True):
        pass

    app = Dex()
    with pytest.raises(TypeError, match="Request"):
        app.get("/value", response=Context)(lambda: Context("GET", "/", {}, "", {}))
    assert app._endpoints == []
    assert app._literal == {}
