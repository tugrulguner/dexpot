from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Annotated

import msgspec
import pytest
from openapi_spec_validator import validate

from dexpot import Dex, Header


class SnapshotBody(msgspec.Struct):
    value: str


_factory_calls = []


def make_default():
    _factory_calls.append(1)
    return "generated"


class FactoryBody(msgspec.Struct):
    value: str = msgspec.field(default_factory=make_default)


class RecursiveBody(msgspec.Struct):
    value: str
    children: list[RecursiveBody] = msgspec.field(default_factory=list)


def exchange(app, body=b"{}"):
    server, client = socket.socketpair()
    with server, client:
        server.settimeout(2)
        client.settimeout(2)
        client.sendall(
            b"POST /value HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        assert app._process(server, b"") == (False, b"")
        response = http.client.HTTPResponse(client)
        response.begin()
        return response.status, json.loads(response.read())


def test_schema_snapshot_survives_annotation_mutation_and_export_does_not_inspect(monkeypatch):
    app = Dex(openapi=True)
    app.post("/value", body=SnapshotBody)(lambda body: body.value)
    monkeypatch.setitem(SnapshotBody.__annotations__, "value", int)

    def forbidden(*args, **kwargs):
        raise AssertionError("export re-inspected a schema")

    monkeypatch.setattr(msgspec.json, "schema_components", forbidden)
    document = app.openapi()
    definition = next(
        value
        for value in document["components"]["schemas"].values()
        if value.get("title") == "SnapshotBody"
    )
    assert definition["properties"]["value"]["type"] == "string"
    assert exchange(app, b'{"value":"ok"}') == (200, "ok")
    validate(document)


def test_default_factory_runs_only_for_actual_request():
    app = Dex(openapi=True)
    app.post("/value", body=FactoryBody)(lambda body: body.value)
    validate(app.openapi())
    assert _factory_calls == []
    assert exchange(app) == (200, "generated")
    assert _factory_calls == [1]


def test_recursive_schemas_and_same_named_types_are_valid_and_separate():
    app = Dex(openapi=True)
    app.post("/recursive", body=RecursiveBody, response=RecursiveBody)(lambda body: body)
    left = msgspec.defstruct("Duplicate", [("left", int)])
    right = msgspec.defstruct("Duplicate", [("right", str)])
    app.post("/left", body=left)(lambda body: None)
    app.post("/right", body=right)(lambda body: None)
    document = app.openapi()
    validate(document)
    duplicates = [
        value
        for value in document["components"]["schemas"].values()
        if value.get("title") == "Duplicate"
    ]
    assert len(duplicates) == 2
    assert {next(iter(value["properties"])) for value in duplicates} == {"left", "right"}


@pytest.mark.parametrize("name", ["accept", "Content-Type", "AUTHORIZATION"])
def test_ignored_openapi_headers_reject_atomically_but_ordinary_apps_work(name):
    def handler(value):
        return value

    handler.__annotations__ = {"value": Annotated[str, Header(name)]}
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="header parameter"):
        app.get("/value")(handler)
    app.get("/value")(lambda: None)
    Dex().get("/value")(handler)
    validate(app.openapi())


def test_invalid_literal_braces_reject_without_reserving_route():
    app = Dex(openapi=True)
    with pytest.raises(TypeError, match="whole-segment"):
        app.get("/literal{x}tail")(lambda: None)
    assert app._endpoints == []


def test_disabled_module_import_and_state_bypass_in_fresh_process():
    code = "import sys;from dexpot import Dex;app=Dex();app.get('/value')(lambda:1);app._compile();assert 'dexpot._openapi' not in sys.modules;assert not hasattr(app,'_openapi_registry')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=8,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_export_reentrancy_failure_is_preserved_and_registration_rolls_back(monkeypatch):
    app = Dex(openapi=True)

    def reenter(*args, **kwargs):
        return app.openapi()

    monkeypatch.setattr(msgspec.json, "schema_components", reenter)
    with pytest.raises(RuntimeError, match="registration"):
        app.post("/value", body=SnapshotBody)(lambda body: None)
    assert app._endpoints == []
    assert app._openapi_registry.operations == []


def test_concurrent_export_waits_for_whole_registration(monkeypatch):
    app = Dex(openapi=True)
    entered, release, exporting = Event(), Event(), Event()
    original = msgspec.json.schema_components

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(msgspec.json, "schema_components", held)

    def export():
        exporting.set()
        return app.openapi()

    with ThreadPoolExecutor(max_workers=2) as pool:
        registration = pool.submit(app.post("/value", body=SnapshotBody), lambda body: None)
        try:
            assert entered.wait(2)
            document = pool.submit(export)
            assert exporting.wait(2)
            assert not document.done()
        finally:
            release.set()
        registration.result(timeout=3)
        result = document.result(timeout=3)
    assert "/value" in result["paths"]
    validate(result)
