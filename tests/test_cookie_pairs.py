import http.client
import json
import socket
from typing import Annotated

from dexpot import Cookie, Dex, Request


def exchange(app: Dex, path: bytes, cookies: tuple[bytes, ...] = ()):
    server, client = socket.socketpair()
    with server, client:
        server.settimeout(2)
        client.settimeout(2)
        client.sendall(
            b"GET "
            + path
            + b" HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
            + b"".join(b"Cookie: " + cookie + b"\r\n" for cookie in cookies)
            + b"\r\n"
        )
        assert app._process(server, b"") == (False, b"")
        response = http.client.HTTPResponse(client)
        response.begin()
        return response.status, json.loads(response.read())


def test_cookie_pairs_preserve_wire_order_and_normalized_header():
    app = Dex()

    @app.get("/prefs")
    def preferences(request: Request):
        pairs = request.cookie_pairs()
        assert type(pairs) is tuple and all(type(pair) is tuple for pair in pairs)
        return {"header": request.headers.get("cookie"), "pairs": pairs}

    assert exchange(app, b"/prefs", (b'a=1; b="%2B+="', b"a=2; A=; b=last")) == (
        200,
        {
            "header": 'a=1; b="%2B+="; a=2; A=; b=last',
            "pairs": [["a", "1"], ["b", "%2B+="], ["a", "2"], ["A", ""], ["b", "last"]],
        },
    )
    assert exchange(app, b"/prefs") == (200, {"header": None, "pairs": []})
    assert exchange(app, b"/prefs", (b"",)) == (200, {"header": "", "pairs": []})


def test_cookie_parsing_is_opt_in_and_keeps_typed_binding_rules():
    app = Dex()

    @app.get("/raw")
    def raw(request: Request):
        return {"header": request.headers.get("cookie")}

    @app.get("/parsed")
    def parsed(request: Request):
        try:
            return {"pairs": request.cookie_pairs()}
        except ValueError as exc:
            return 422, {"detail": str(exc)}

    @app.get("/typed")
    def typed(theme: Annotated[str, Cookie("theme")]):
        return {"theme": theme}

    for malformed in (b'theme=dark; hidden="private', b"theme=dark;", b"theme=dark; bad name=x"):
        assert exchange(app, b"/raw", (malformed,)) == (200, {"header": malformed.decode()})
        for path in (b"/parsed", b"/typed"):
            assert exchange(app, path, (malformed,)) == (422, {"detail": "invalid cookie header"})
    assert exchange(app, b"/typed", (b'theme="dark"; x=1; x=2',)) == (200, {"theme": "dark"})
    assert exchange(app, b"/typed", (b"theme=dark", b"theme=dark")) == (
        422,
        {"detail": "cookie parameter 'theme': repeated"},
    )
