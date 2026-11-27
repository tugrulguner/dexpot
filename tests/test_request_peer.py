import http.client
import json
import socket

import pytest

from dexpot import Dex, Request


def exchange(app: Dex, server: socket.socket, client: socket.socket, path: bytes):
    server.settimeout(2)
    client.settimeout(2)
    client.sendall(
        b"GET " + path + b" HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n"
        b'Forwarded: for="192.0.2.20:1234"\r\nX-Forwarded-For: 192.0.2.21\r\n'
        b"X-Real-IP: 192.0.2.22\r\n\r\n"
    )
    assert app._process(server, b"") == (True, b"")
    response = http.client.HTTPResponse(client)
    response.begin()
    return response.status, json.loads(response.read())


@pytest.mark.parametrize(
    ("family", "host"), [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
)
def test_request_peer_reports_tcp_endpoint_on_keep_alive(family: socket.AddressFamily, host: str):
    app = Dex()

    @app.get("/peer")
    def peer(request: Request):
        return {"peer": request.peer, "forwarded": request.headers["x-forwarded-for"]}

    with socket.socket(family, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((host, 0))
        except OSError:
            if family == socket.AF_INET:
                raise
            pytest.skip("IPv6 loopback unavailable")
        listener.listen()
        listener.settimeout(2)
        with socket.socket(family, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(listener.getsockname())
            server, _ = listener.accept()
            with server:
                expected = (
                    200,
                    {"peer": list(client.getsockname()[:2]), "forwarded": "192.0.2.21"},
                )
                assert exchange(app, server, client, b"/peer") == expected
                assert exchange(app, server, client, b"/peer") == expected


def test_manual_and_non_ip_requests_have_no_peer():
    app = Dex()

    @app.get("/peer")
    def peer(request: Request):
        return {"peer": request.peer}

    assert Request("GET", "/", {}, "", {}).peer is None
    server, client = socket.socketpair()
    with server, client:
        if server.family in (socket.AF_INET, socket.AF_INET6):
            return
        assert exchange(app, server, client, b"/peer") == (200, {"peer": None})


def test_lookup_failure_is_optional_and_requestless_routes_skip_it(monkeypatch: pytest.MonkeyPatch):
    app = Dex()

    @app.get("/peer")
    def peer(request: Request):
        return {"peer": request.peer}

    @app.get("/plain")
    def plain():
        return {"ok": True}

    calls = 0

    def unavailable(_conn: socket.socket):
        nonlocal calls
        calls += 1
        raise OSError("peer unavailable")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            server, _ = listener.accept()
            with server:
                monkeypatch.setattr(socket.socket, "getpeername", unavailable)
                assert exchange(app, server, client, b"/plain") == (200, {"ok": True})
                assert calls == 0
                assert exchange(app, server, client, b"/peer") == (200, {"peer": None})
                assert calls == 1
