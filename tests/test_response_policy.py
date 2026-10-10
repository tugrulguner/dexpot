"""Response contracts exercised through real sockets and the connection owner."""

import http.client
import socket
import threading
from contextlib import contextmanager
from datetime import UTC
from typing import Any, cast

import msgspec
import pytest

from dexpot import Dex


@contextmanager
def connection(app):
    server, client = socket.socketpair()
    client.settimeout(3)
    app._compile()
    owner = threading.Thread(target=app._own_connection, args=(server, b""), daemon=True)
    owner.start()
    try:
        yield client
    finally:
        client.close()
        owner.join(timeout=3)
        assert not owner.is_alive()


def request(app, path="/value"):
    with connection(app) as sock:
        sock.sendall(f"GET {path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode())
        response = http.client.HTTPResponse(sock)
        response.begin()
        return response.status, dict(response.getheaders()), response.read()


class FloatOutput(msgspec.Struct):
    value: float


class OptionalFloatOutput(msgspec.Struct):
    value: float | None


class NestedFloatOutput(msgspec.Struct):
    values: list[OptionalFloatOutput]


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("shape", ["required", "optional", "nested"])
def test_nonfinite_checked_float_fails_before_success_bytes(number, shape):
    schema, value = {
        "required": (FloatOutput, FloatOutput(number)),
        "optional": (OptionalFloatOutput, OptionalFloatOutput(number)),
        "nested": (NestedFloatOutput, NestedFloatOutput([OptionalFloatOutput(number)])),
    }[shape]
    app = Dex()
    app.get("/value", response=schema)(lambda value=value: value)
    status, headers, body = request(app)
    assert status == 500
    assert body == b'{"detail":"internal server error"}'
    assert headers["Content-Length"] == str(len(body))


class Public(msgspec.Struct):
    name: str


class Private(Public):
    secret: str


class Container(msgspec.Struct):
    entries: list[Public]


@pytest.mark.parametrize(
    "value",
    [
        Public(cast(Any, 7)),
        Container([Public(cast(Any, 7))]),
        [Public(cast(Any, 7))],
        {},
        {"name": None},
    ],
)
def test_malformed_existing_structs_and_missing_fields(value):
    schema = (
        Container
        if isinstance(value, Container)
        else list[Public]
        if isinstance(value, list)
        else Public
    )
    app = Dex()
    app.get("/value", response=schema)(lambda value=value: value)
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


@pytest.mark.parametrize(
    "value", [{"name": "alice", "secret": "private"}, Private("alice", "private")]
)
def test_public_schema_projects_extra_fields(value):
    app = Dex()
    app.get("/value", response=Public)(lambda value=value: value)
    assert request(app)[::2] == (200, b'{"name":"alice"}')


def test_unsupported_schema_registration_is_atomic():
    class Hook(msgspec.Struct):
        value: int

        def __post_init__(self):
            self.value = cast(Any, "invalid")

    class Custom:
        pass

    for schema in (Hook, list[Hook], Custom, int | str | Custom):
        app = Dex()
        with pytest.raises(TypeError):
            app.get("/value", response=schema)(lambda: {})
        assert app._endpoints == []
        assert app._literal == {}
        assert app._parametric == []
        app.get("/value")(lambda: {})
        assert request(app)[0] == 200


def test_response_envelopes_and_duplicate_header_snapshot():
    from dexpot import RawResponse, Response

    original = [["Set-Cookie", "a=1"], ["Set-Cookie", "b=2"]]
    output = Response({"name": "alice", "secret": "hidden"}, 201, cast(Any, original))
    original[0][1] = "changed"
    original.append(["X-New", "no"])
    assert output.headers == (("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"))
    with pytest.raises(AttributeError):
        output.status = 202  # pyright: ignore[reportAttributeAccessIssue] -- test frozen API
    app = Dex()
    app.get("/value", response=Public)(lambda: output)
    with connection(app) as sock:
        sock.sendall(b"GET /value HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        response = http.client.HTTPResponse(sock)
        response.begin()
        assert response.status == 201
        assert response.msg.get_all("Set-Cookie") == ["a=1", "b=2"]
        assert response.read() == b'{"name":"alice"}'
    raw = Dex()
    raw.get("/value")(lambda: RawResponse(b"hello", 202, {"X-Test": "yes"}, "text/plain"))
    status, headers, body = request(raw)
    assert (status, body) == (202, b"hello")
    assert headers["Content-Type"] == "text/plain"
    assert headers["X-Test"] == "yes"


@pytest.mark.parametrize("status", [204, 205, 304])
def test_explicit_empty_responses_on_checked_routes(status):
    from dexpot import Response

    app = Dex()
    app.get("/value", response=Public)(lambda: Response(status=status))
    code, headers, body = request(app)
    assert (code, body) == (status, b"")
    assert headers.get("Content-Length") == ("0" if status == 205 else None)


@pytest.mark.parametrize("status", [True, False, 199, 100, 600, "200", 200.0])
def test_invalid_envelope_status_is_sanitized(status):
    from dexpot import Response

    app = Dex()
    app.get("/value")(lambda: Response({}, status))
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


@pytest.mark.parametrize(
    "headers",
    [
        {name: "x"}
        for name in (
            "Content-Length",
            "Transfer-Encoding",
            "Connection",
            "Keep-Alive",
            "Upgrade",
            "Trailer",
            "TE",
            "Server",
            "Content-Type",
            "Proxy-Connection",
            "bad name",
            "é",
            "",
        )
    ]
    + [{"X-Test": value} for value in ("a\r\nb", "a\x00", "a\t", "a\x7f", "😀", 42)]
    + [[("X-Test", "v")] * 65, {"X-Test": "v" * 16384}],
)
def test_unsafe_headers_fail_closed(headers):
    from dexpot import Response

    app = Dex()
    app.get("/value")(lambda: Response({}, headers=headers))
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


@pytest.mark.parametrize("body", ["text", bytearray(b"x"), memoryview(b"x"), None])
def test_raw_requires_bytes(body):
    from dexpot import RawResponse

    app = Dex()
    app.get("/value")(lambda: RawResponse(body))
    assert request(app)[0] == 500


def test_raw_cannot_bypass_checked_schema():
    from dexpot import RawResponse

    app = Dex()
    app.get("/value", response=Public)(lambda: RawResponse(b'{"name":"alice"}'))
    assert request(app)[0] == 500


class InvalidDefault(msgspec.Struct):
    value: int = cast(Any, "secret")


class NonfiniteDefault(msgspec.Struct):
    value: float | None = float("nan")


@pytest.mark.parametrize("schema", [InvalidDefault, NonfiniteDefault])
def test_defaults_cannot_corrupt_final_json(schema):
    app = Dex()
    with pytest.raises(TypeError, match="invalid checked response default"):
        app.get("/value", response=schema)(lambda: {})
    assert not app._endpoints


@pytest.mark.parametrize("value", ["secret", float("nan"), float("inf")])
def test_invalid_application_factory_result_is_sanitized(value):
    class WithFactory(msgspec.Struct):
        number: float = msgspec.field(default_factory=lambda: value)

    app = Dex()
    app.get("/value", response=WithFactory)(lambda: {})
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


def test_application_factory_is_not_invoked_during_registration():
    calls = []

    def factory():
        calls.append(1)
        return Private("alice", "private")

    class WithFactory(msgspec.Struct):
        value: Public = msgspec.field(default_factory=factory)

    app = Dex()
    app.get("/value", response=WithFactory)(lambda: {})
    assert not calls
    assert request(app)[::2] == (200, b'{"value":{"name":"alice"}}')
    assert calls == [1]


def test_invalid_builtin_factory_default_is_rejected():
    class WithFactory(msgspec.Struct):
        value: int = cast(Any, msgspec.field(default_factory=list))

    app = Dex()
    with pytest.raises(TypeError, match="invalid checked response default"):
        app.get("/value", response=WithFactory)(lambda: {})
    assert not app._endpoints


@pytest.mark.parametrize("default", ["hidden-invalid", True, None])
def test_invalid_omitted_defaults_are_rejected_atomically(default):
    class Omitted(msgspec.Struct, omit_defaults=True):
        count: int = cast(Any, default)

    app = Dex()
    with pytest.raises(TypeError):
        app.get("/value", response=Omitted)(lambda: {})
    assert not app._endpoints
    assert not app._literal


def test_default_factory_cannot_introduce_request_context():
    from dexpot import Request

    class WithContext(msgspec.Struct):
        context: Any = msgspec.field(
            default_factory=lambda: Request("GET", "/", {"Authorization": "secret"}, "", {})
        )

    app = Dex()
    app.get("/value", response=WithContext)(lambda: {})
    assert request(app)[::2] == (500, b'{"detail":"internal server error"}')


def test_default_factory_values_are_projected_to_nested_public_schema():
    class WithDefault(msgspec.Struct):
        value: Public = msgspec.field(default_factory=lambda: Private("alice", "private"))

    app = Dex()
    app.get("/value", response=WithDefault)(lambda: {})
    assert request(app)[::2] == (200, b'{"value":{"name":"alice"}}')


def test_immutable_nested_default_is_projected():
    class FrozenPublic(msgspec.Struct, frozen=True):
        name: str

    class FrozenPrivate(FrozenPublic, frozen=True):
        secret: str

    class WithDefault(msgspec.Struct):
        value: FrozenPublic = FrozenPrivate("alice", "private")

    app = Dex()
    app.get("/value", response=WithDefault)(lambda: {})
    assert request(app)[::2] == (200, b'{"value":{"name":"alice"}}')


def test_guard_does_not_resolve_struct_annotations(monkeypatch):
    from dexpot._plans import _contains_request

    def forbidden(*args, **kwargs):
        raise AssertionError("response traversal must use compiled field names")

    monkeypatch.setattr(msgspec.structs, "fields", forbidden)
    assert not _contains_request(Container([Public("ok")]), set())


@pytest.mark.parametrize(
    "schema,value,expected",
    [
        (int, "1", None),
        (int, True, None),
        (float, 1, b"1.0"),
        (str | int, "ok", b'"ok"'),
        (str | int, [], None),
        (OptionalFloatOutput, {"value": None}, b'{"value":null}'),
        (OptionalFloatOutput, {}, None),
        (
            Container,
            {"entries": [{"name": "ok", "secret": "hidden"}]},
            b'{"entries":[{"name":"ok"}]}',
        ),
    ],
)
def test_strict_checked_values(schema, value, expected):
    app = Dex()
    app.get("/value", response=schema)(lambda value=value: value)
    assert request(app)[::2] == (
        (500, b'{"detail":"internal server error"}') if expected is None else (200, expected)
    )


def test_native_schema_shapes():
    from datetime import datetime
    from enum import Enum
    from typing import Annotated
    from uuid import UUID

    class Color(str, Enum):  # noqa: UP042 -- cover traditional string Enum schemas
        RED = "red"

    class Tagged(msgspec.Struct, tag=True, rename={"name": "publicName"}, omit_defaults=True):
        name: str
        count: Annotated[int, msgspec.Meta(ge=1)] = 1

    class Other(msgspec.Struct, tag=True):
        value: str

    class Rich(msgspec.Struct):
        blob: bytes
        date: datetime
        uid: UUID
        color: Color

    cases = [
        (
            Tagged | Other,
            {"type": "Tagged", "publicName": "ok", "secret": "hidden"},
            {"type": "Tagged", "publicName": "ok"},
        ),
        (
            Rich,
            Rich(b"abc", datetime(2026, 1, 1, tzinfo=UTC), UUID(int=0), Color.RED),
            {
                "blob": "YWJj",
                "date": "2026-01-01T00:00:00Z",
                "uid": str(UUID(int=0)),
                "color": "red",
            },
        ),
    ]
    for schema, value, expected in cases:
        app = Dex()
        app.get("/value", response=schema)(lambda value=value: value)
        status, _, body = request(app)
        assert status == 200
        assert msgspec.json.decode(body) == expected
        msgspec.json.decode(body, type=schema)
    for value in ({"type": "Tagged", "publicName": "ok", "count": 0}, {"type": "Unknown"}):
        app = Dex()
        app.get("/value", response=Tagged | Other)(lambda value=value: value)
        assert request(app)[0] == 500


def test_any_and_generic_policy():
    from typing import Any

    for value in (float("nan"), {"nested": [float("inf")]}):
        checked = Dex()
        checked.get("/value", response=Any)(lambda value=value: value)
        assert request(checked)[0] == 500
    generic = Dex()
    generic.get("/value")(lambda: {"extra": "retained", "value": float("nan")})
    assert request(generic)[::2] == (200, b'{"extra":"retained","value":null}')


def test_checked_requestless_guard_and_cycles(monkeypatch):
    from dataclasses import dataclass
    from enum import Enum
    from typing import Any

    import dexpot.app as app_module
    from dexpot import Request

    context = Request("GET", "/", {}, "", {})

    @dataclass
    class Box:
        value: object

    class Choice(Enum):
        VALUE = context

    cycle = []
    cycle.append(cycle)
    cycle.append(context)
    values = [
        context,
        {"nested": context},
        Box(context),
        Choice.VALUE,
        cycle,
        Container([cast(Any, context)]),
        {Choice.VALUE: "key"},
    ]

    def forbidden(*args, **kwargs):
        raise AssertionError("requestless handler allocated Request")

    monkeypatch.setattr(app_module, "Request", forbidden)
    for value in values:
        app = Dex()
        app.get("/value", response=Any)(lambda value=value: value)
        assert request(app)[0] == 500
    app = Dex()
    app.get("/value", response=Public)(lambda: Public("ok"))
    assert request(app)[0] == 200


@pytest.mark.parametrize("content_type", ["", "x\r\ny", "x\x00", "😀", "x" * 257])
def test_raw_content_type_is_validated(content_type):
    from dexpot import RawResponse

    app = Dex()
    app.get("/value")(lambda: RawResponse(b"ok", content_type=content_type))
    assert request(app)[0] == 500


def test_pipelining_recovery_empty_and_raw_framing():
    from dexpot import RawResponse, Response

    app = Dex()
    app.get("/bad", response=Public)(lambda: Response({"name": 1}, headers={"X-Secret": "hidden"}))
    app.get("/tuple", response=Public)(lambda: (201, {"name": "ok", "secret": "hidden"}))
    app.get("/raw")(lambda: RawResponse(b"hello", content_type="text/plain"))
    app.get("/empty")(lambda: RawResponse())
    for code in (204, 205, 304):
        app.get(f"/empty/{code}")(lambda code=code: Response(status=code))
    paths = ["/bad", "/empty/204", "/empty/205", "/empty/304", "/empty", "/raw", "/tuple"]
    with connection(app) as sock:
        sock.sendall(
            b"".join(f"GET {path} HTTP/1.1\r\nHost: test\r\n\r\n".encode() for path in paths)
        )
        # One buffered stream avoids HTTPResponse read-ahead across pipelined messages.
        stream = sock.makefile("rb")
        try:
            for expected_code, expected_body in [
                (500, b'{"detail":"internal server error"}'),
                (204, b""),
                (205, b""),
                (304, b""),
                (200, b""),
                (200, b"hello"),
                (201, b'{"name":"ok"}'),
            ]:
                assert int(stream.readline().split()[1]) == expected_code
                headers = {}
                while (line := stream.readline()) != b"\r\n":
                    name, value = line.rstrip().split(b": ", 1)
                    headers[name] = value
                assert b"X-Secret" not in headers
                length = int(headers.get(b"Content-Length", b"0"))
                assert stream.read(length) == expected_body
                if expected_code in (204, 304):
                    assert b"Content-Length" not in headers
        finally:
            stream.close()


def test_head_envelope_suppresses_body():
    from dexpot import RawResponse

    app = Dex()
    app._register("HEAD", "/value", lambda: RawResponse(b"secret"), None, None)
    with connection(app) as sock:
        sock.sendall(b"HEAD /value HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        chunks = []
        while chunk := sock.recv(4096):
            chunks.append(chunk)
    head, body = b"".join(chunks).split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200")
    assert body == b""


def test_runnable_example_through_connection_owner():
    import runpy
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "examples" / "response_policy.py"
    app = runpy.run_path(str(example))["app"]
    assert request(app, "/public")[::2] == (201, b'{"name":"alice"}')
    assert request(app, "/invalid")[::2] == (500, b'{"detail":"internal server error"}')
    assert request(app, "/raw")[::2] == (200, b"hello\n")
    assert request(app, "/empty")[::2] == (204, b"")
    assert request(app, "/tuple")[::2] == (202, b'{"name":"legacy"}')


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_crud_example_preserves_not_found_response(method):
    import runpy
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "examples" / "typed_crud.py"
    app = runpy.run_path(str(example))["app"]
    body = b'{"name":"missing","price":1.0}' if method == "PUT" else b""
    with connection(app) as sock:
        sock.sendall(
            f"{method} /items/999 HTTP/1.1\r\nHost: test\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        response = http.client.HTTPResponse(sock)
        response.begin()
        assert response.status == 404
        assert response.read() == b'{"detail":"item not found"}'
