import http.client
import json
import socket
from typing import Annotated

from dexpot import Dex, Query, Request


def exchange(app: Dex, target: bytes):
    server, client = socket.socketpair()
    with server, client:
        server.settimeout(2)
        client.settimeout(2)
        client.sendall(
            b"GET " + target + b" HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        assert app._process(server, b"") == (False, b"")
        response = http.client.HTTPResponse(client)
        response.begin()
        return response.status, json.loads(response.read())


def test_repeated_integer_query_preserves_order_and_duplicates():
    app = Dex()

    @app.get("/filter")
    def filter_items(ids: Annotated[list[int], Query("id")]):
        return {"ids": ids}

    assert exchange(app, b"/filter?id=7&%69d=2&id=7") == (200, {"ids": [7, 2, 7]})


def test_defaults_are_snapshotted_and_each_request_owns_its_list():
    app = Dex(openapi=True)
    default = [3]

    @app.get("/filter")
    def filter_items(ids: Annotated[list[int], Query("id")] = default):
        ids.append(4)
        return ids

    default.append(9)
    document = app.openapi()
    from openapi_spec_validator import validate

    validate(document)
    assert document["paths"]["/filter"]["get"]["parameters"] == [
        {
            "name": "id",
            "in": "query",
            "required": False,
            "style": "form",
            "explode": True,
            "schema": {"type": "array", "items": {"type": "integer"}, "default": [3]},
        }
    ]
    assert exchange(app, b"/filter") == (200, [3, 4])
    assert exchange(app, b"/filter?id=6") == (200, [6, 4])
    assert exchange(app, b"/filter") == (200, [3, 4])


def test_strings_preserve_empty_items_and_raw_query():
    app = Dex()

    @app.get("/filter")
    def filter_items(tags: Annotated[list[str], Query("tag")], request: Request):
        return {"tags": tags, "raw": request.query}

    assert exchange(app, b"/filter") == (422, {"detail": "query parameter 'tag': missing"})
    query = b"tag&tag=&tag=one,two&tag=a+b&tag=a%2Bb"
    assert exchange(app, b"/filter?" + query) == (
        200,
        {"tags": ["", "", "one,two", "a b", "a+b"], "raw": query.decode()},
    )


def test_first_invalid_item_is_sanitized_and_skips_handler():
    app = Dex()
    calls = []

    @app.get("/filter")
    def filter_items(ids: Annotated[list[int], Query("id")]):
        calls.append(ids)
        return ids

    for query, reason in [(b"id=1&id=&id=%FF", "invalid"), (b"id=%FF&id=bad", "encoding")]:
        assert exchange(app, b"/filter?" + query) == (
            422,
            {"detail": f"query parameter 'id': {reason}"},
        )
    assert exchange(app, b"/filter?id=%GG") == (400, {"detail": "invalid request target escape"})
    assert calls == []
    assert exchange(app, b"/filter?id=1") == (200, [1])
