from __future__ import annotations

import http.client
import socket

import msgspec
import pytest
from jsonschema import Draft202012Validator

from dexpot import Dex
from test_openapi_annotation_owners import fixture_type


def exchange(app, payload):
    data = msgspec.json.encode(payload)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            server, _ = listener.accept()
            with server:
                server.settimeout(2)
                client.sendall(
                    b"POST /value HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\n\r\n"
                    + data
                )
                app._process(server, b"")
                response = http.client.HTTPResponse(client)
                response.begin()
                return response.status, msgspec.json.decode(response.read())


@pytest.mark.parametrize("wrapped", [False, True])
def test_static_attrs_schema_matches_http_and_rejected_inputs_have_no_handler_effects(
    monkeypatch, wrapped
):
    module, schema = fixture_type(monkeypatch, "attrs", wrapped, False)
    app = Dex(openapi=True)
    called = []

    @app.post("/value", body=schema)
    def handler(body):
        value = msgspec.to_builtins(body)
        called.append(value)
        return value

    document = app.openapi()
    body_schema = document["paths"]["/value"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    validator = Draft202012Validator({"allOf": [body_schema], "components": document["components"]})
    for value, expected in [("ok", 200), ("x", 422)]:
        payload = {"value": value}
        if wrapped:
            payload = {"value": payload}
        assert validator.is_valid(payload) is (expected == 200)
        status, result = exchange(app, payload)
        assert status == expected
        if status == 200:
            assert result == payload
            assert called == [payload]
        else:
            assert "detail" in result
            assert len(called) == 1
    assert module.calls == []
