from __future__ import annotations

import socket
import subprocess
import sys
import time
import typing
from enum import Enum
from typing import Any, Literal, NewType

import httpx
import pytest

from dexpot import Dex


def test_path_annotation_float_is_rejected_before_route_publication() -> None:
    app = Dex()
    invoked = False

    def bad(item: float) -> str:
        nonlocal invoked
        invoked = True
        return str(item)

    with pytest.raises(TypeError, match=r"path parameter 'item'.*str.*int.*Any"):
        app.get("/items/{item}")(bad)

    assert not invoked
    assert app._endpoints == []
    assert app._literal == {}
    assert app._parametric == []

    @app.get("/items/{value}")
    def good(value: int) -> str:
        return str(value)

    assert good.__name__ == "good"
    assert len(app._endpoints) == 1
    assert app._compile().endpoints == (app._endpoints[0],)


@pytest.mark.parametrize(
    "annotation",
    [
        bool,
        float,
        None,
        list[int],
        typing.Annotated[int, "meta"],
        int | None,
        Literal[1],
        NewType("UserId", int),
        Enum("Status", {"OK": 1}),
    ],
)
def test_path_annotation_rejects_unsupported_types(annotation: object) -> None:
    app = Dex()

    def handler(value):
        return str(value)

    handler.__annotations__["value"] = annotation

    with pytest.raises(TypeError, match=r"path parameter 'value'.*str.*int.*Any"):
        app.get("/x/{value}")(handler)
    assert app._endpoints == []
    handler.__annotations__["value"] = str
    app.get("/x/{value}")(handler)
    assert len(app._compile().endpoints) == 1


@pytest.mark.parametrize("annotation", [str, int, Any])
def test_supported_path_annotations_register(annotation: object) -> None:
    app = Dex()

    def handler(value):
        return str(value)

    handler.__annotations__["value"] = annotation
    app.get("/x/{value}")(handler)
    assert len(app._endpoints) == 1


def test_unannotated_path_preserves_raw_value() -> None:
    app = Dex()

    @app.get("/x/{value}")
    def handler(value):
        return value

    endpoint = app._compile().endpoints[0]
    assert endpoint.int_captures == ()
    assert endpoint.invoke(["007"], None) == "007"


def test_int_and_raw_path_annotations_over_real_http() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    source = f"""
from typing import Any
import msgspec
from dexpot import Dex, Request
app = Dex()
calls = 0
@app.get("/int/{{value}}")
def integer(value: int):
    global calls
    calls += 1
    return {{"value": value, "calls": calls}}
@app.get("/raw/{{value}}")
def raw(value): return {{"value": value}}
@app.get("/string/{{value}}")
def string(value: str): return {{"value": value}}
@app.get("/any/{{value}}")
def any_value(value: Any): return {{"value": value}}
class Payload(msgspec.Struct):
    amount: int
@app.post("/mixed/{{category}}/{{item_id}}", body=Payload)
def mixed(payload: Payload, item_id: int, *, category: str, request: Request, suffix="!"):
    return {{"id": item_id, "category": category, "amount": payload.amount,
            "suffix": suffix, "params": request.params}}
app.serve(host="127.0.0.1", port={port})
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 8
        while True:
            try:
                response = httpx.get(f"{base}/raw/ready", timeout=0.2)
                assert response.status_code == 200
                break
            except httpx.HTTPError:
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.02)
        with httpx.Client(base_url=base) as client:
            first = client.get("/int/007")
            assert first.status_code == 200
            assert first.json() == {"value": 7, "calls": 1}
            for route in ("raw", "string", "any"):
                response = client.get(f"/{route}/007")
                assert response.status_code == 200
                assert response.json() == {"value": "007"}
            invalid = client.get("/int/not-an-int")
            assert invalid.status_code == 422
            assert invalid.json() == {"detail": "invalid int for value"}
            # Recovery also proves invalid input did not invoke the handler.
            assert client.get("/int/8").json() == {"value": 8, "calls": 2}
            mixed = client.post("/mixed/tea/007", json={"amount": 3})
            assert mixed.status_code == 200
            assert mixed.json() == {
                "id": 7,
                "category": "tea",
                "amount": 3,
                "suffix": "!",
                "params": {"category": "tea", "item_id": "007"},
            }
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)
