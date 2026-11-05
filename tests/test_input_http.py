"""Socket-level regression matrix for explicit scalar sources."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture(scope="module")
def source_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env["DEXPOT_EXAMPLE_PORT"] = str(port)
    env["DEXPOT_WORKERS"] = "1"
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("typed_inputs_app.py"))],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"fixture exited: {process.communicate()!r}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("source server failed readiness")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            yield client
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)
            pytest.fail("source server failed cleanup")


@pytest.mark.parametrize("source", ["q", "h", "c"])
@pytest.mark.parametrize(
    "kind,text,value",
    [
        ("str", "hello", "hello"),
        ("int", "7", 7),
        ("float", "1.5", 1.5),
        ("bool", "TrUe", True),
    ],
)
def test_explicit_scalar_sources_bind_actual_argument_types(
    source_server, source, kind, text, value
):
    kwargs = (
        {"params": {"value": text}}
        if source == "q"
        else {"headers": {"x-value": text} if source == "h" else {"Cookie": "value=" + text}}
    )
    response = source_server.get(f"/{source}/{kind}", **kwargs)
    assert response.status_code == 200
    assert response.json() == {"value": value, "type": kind}


@pytest.mark.parametrize(
    "path,headers,status,expected",
    [
        ("/q/required", {}, 422, {"detail": "query parameter 'value': missing"}),
        ("/q/str?value=", {}, 200, {"value": "", "type": "str"}),
        ("/q/str?value", {}, 200, {"value": "", "type": "str"}),
        ("/q/str?value=null", {}, 200, {"value": "null", "type": "str"}),
        ("/q/int?value=", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/int?value=1&%76alue=1", {}, 422, {"detail": "query parameter 'value': repeated"}),
        ("/q/int?ignored=1&ignored=2&value=3", {}, 200, {"value": 3, "type": "int"}),
        ("/q/int?value=%GG", {}, 400, {"detail": "invalid request target escape"}),
        ("/q/str?value=%FF", {}, 422, {"detail": "query parameter 'value': encoding"}),
        ("/q/int?ignored=%FF&value=3", {}, 200, {"value": 3, "type": "int"}),
        ("/q/int?%FF=x&value=3", {}, 422, {"detail": "invalid query encoding"}),
        ("/q/str?value=a+b", {}, 200, {"value": "a b", "type": "str"}),
        ("/q/str?value=a%2Bb", {}, 200, {"value": "a+b", "type": "str"}),
        ("/q/int?value=%2B007", {}, 200, {"value": 7, "type": "int"}),
        ("/q/int?value=+007", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/int?value=%D9%A1", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/int?value=1_0", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/int?value=%207", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/float?value=.5", {}, 200, {"value": 0.5, "type": "float"}),
        ("/q/float?value=1.", {}, 200, {"value": 1.0, "type": "float"}),
        ("/q/float?value=NaN", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/float?value=Infinity", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/float?value=1e9999", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/float?value=-1e-9999", {}, 200, {"value": -0.0, "type": "float"}),
        ("/q/bool?value=yes", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/bool?value=1", {}, 422, {"detail": "query parameter 'value': invalid"}),
        ("/q/bool?value=false", {}, 200, {"value": False, "type": "bool"}),
        ("/q/required?Value=other", {}, 422, {"detail": "query parameter 'value': missing"}),
        ("/q/str?value=one;two", {}, 200, {"value": "one;two", "type": "str"}),
        ("/q/int?&&value=3&&", {}, 200, {"value": 3, "type": "int"}),
        ("/h/required", {}, 422, {"detail": "header parameter 'x-value': missing"}),
        ("/h/str", {"X-Value": ""}, 200, {"value": "", "type": "str"}),
        ("/h/int", {"X-Value": " 7 "}, 200, {"value": 7, "type": "int"}),
        ("/h/str", [("X-Value", "1"), ("x-value", "2")], 200, {"value": "1, 2", "type": "str"}),
        ("/h/int", {"X-Value": "1, 2"}, 422, {"detail": "header parameter 'x-value': invalid"}),
        ("/h/str?%FF=x", {}, 200, {"value": "fallback", "type": "str"}),
        ("/c/required", {}, 422, {"detail": "cookie parameter 'value': missing"}),
        ("/c/str", {"Cookie": "value="}, 200, {"value": "", "type": "str"}),
        ("/c/str", {"Cookie": 'value=""'}, 200, {"value": "", "type": "str"}),
        ("/c/str", {"Cookie": 'value="dark"'}, 200, {"value": "dark", "type": "str"}),
        (
            "/c/str",
            {"Cookie": "value=one; value=one"},
            422,
            {"detail": "cookie parameter 'value': repeated"},
        ),
        (
            "/c/str",
            [("Cookie", "value=one"), ("Cookie", "value=two")],
            422,
            {"detail": "cookie parameter 'value': repeated"},
        ),
        ("/c/str", {"Cookie": "Value=other"}, 200, {"value": "fallback", "type": "str"}),
        ("/c/str", {"Cookie": "value=a+b%2Bc"}, 200, {"value": "a+b%2Bc", "type": "str"}),
        ("/c/int", {"Cookie": "other=one ; value=2"}, 200, {"value": 2, "type": "int"}),
        ("/c/int", {"Cookie": "value= 2"}, 422, {"detail": "invalid cookie header"}),
        ("/c/str", {"Cookie": 'value="a;b"'}, 422, {"detail": "invalid cookie header"}),
        ("/c/str", {"Cookie": 'value="bad'}, 422, {"detail": "invalid cookie header"}),
        ("/c/str", {"Cookie": "value=one;;"}, 422, {"detail": "invalid cookie header"}),
        (
            "/c/str",
            {"Cookie": "other=bad,pair; value=good"},
            422,
            {"detail": "invalid cookie header"},
        ),
        (
            "/c/str",
            {"Cookie": "other=1; other=2; value=good"},
            200,
            {"value": "good", "type": "str"},
        ),
        (
            "/ordered",
            {"X-Value": "bad", "Cookie": "malformed"},
            422,
            {"detail": "header parameter 'x-value': invalid"},
        ),
        ("/absent?value=%FF", {}, 404, {"detail": "not found"}),
    ],
)
def test_input_wire_contract(source_server, path, headers, status, expected):
    import http.client
    import json

    before = source_server.get("/stats").json()["calls"]
    connection = http.client.HTTPConnection(
        source_server.base_url.host, source_server.base_url.port, timeout=3
    )
    try:
        connection.putrequest("GET", path)
        for name, value in headers.items() if isinstance(headers, dict) else headers:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == status
        assert payload == expected
    finally:
        connection.close()
    if status >= 400:
        assert source_server.get("/stats").json()["calls"] == before


def test_body_binding_precedence_and_raw_request_are_preserved(source_server):
    response = source_server.post(
        "/mixed/7?limit=2&ignored=%FF",
        json={"name": "tea"},
        headers={"X-Request-ID": "trace"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "limit": 2,
        "name": "tea",
        "id": 7,
        "request_id": "trace",
        "raw_query": "limit=2&ignored=%FF",
        "params": {"item_id": "7"},
        "same_body": True,
    }
    invalid_path = source_server.post("/mixed/bad?limit=bad", json={"name": False})
    assert invalid_path.status_code == 422
    assert invalid_path.json() == {"detail": "invalid int for item_id"}
    invalid_body = source_server.post("/mixed/7?limit=bad", json={"name": False})
    assert invalid_body.status_code == 422
    assert "query parameter" not in invalid_body.json()["detail"]
    assert "name" in invalid_body.json()["detail"]


def test_head_keeps_method_matching_and_body_suppression(source_server):
    response = source_server.head("/q/int?value=bad")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.content == b""


def test_input_error_recovers_on_same_pipelined_connection(source_server):
    import json

    with socket.create_connection(
        (source_server.base_url.host, source_server.base_url.port), timeout=3
    ) as conn:
        conn.sendall(
            b"GET /q/int?value=bad HTTP/1.1\r\nHost: localhost\r\n\r\n"
            b"GET /q/int?value=9 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        with conn.makefile("rb") as stream:

            def read_response():
                status = int(stream.readline().split()[1])
                headers = {}
                while (line := stream.readline()) != b"\r\n":
                    assert line
                    name, _, value = line.partition(b":")
                    headers[name.lower()] = value.strip()
                return status, json.loads(stream.read(int(headers[b"content-length"])))

            assert read_response() == (422, {"detail": "query parameter 'value': invalid"})
            assert read_response() == (200, {"value": 9, "type": "int"})


def test_concurrent_connections_do_not_share_input_values(source_server):
    from concurrent.futures import ThreadPoolExecutor

    def request(index):
        response = source_server.get("/q/int", params={"value": index})
        assert response.status_code == 200
        return response.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        observed = list(pool.map(request, range(32)))
    assert observed == [{"value": index, "type": "int"} for index in range(32)]
