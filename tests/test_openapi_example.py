"""Validate the actual exported artifact and its documented HTTP consumer."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/openapi.py"


def test_example_exports_valid_openapi_without_listening_and_refuses_overwrite(tmp_path):
    target = tmp_path / "openapi.json"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    run = subprocess.run(
        [sys.executable, str(EXAMPLE), "--export", str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert run.returncode == 0, run.stderr
    document = json.loads(target.read_text())
    validate(document)
    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == "development"
    assert set(document["paths"]) == {"/items/{item_id}", "/stats", "/openapi.json"}
    operation = document["paths"]["/items/{item_id}"]["post"]
    assert "200" not in operation["responses"] and "201" not in operation["responses"]
    fields = {(field["in"], field["name"]): field for field in operation["parameters"]}
    assert fields[("path", "item_id")]["required"]
    assert fields[("query", "limit")]["schema"]["default"] == 20
    assert fields[("header", "x-request-id")]["required"]
    assert fields[("cookie", "theme")]["schema"]["default"] == "light"
    assert "internal_note" not in target.read_text()
    before = target.read_bytes()
    retry = subprocess.run(
        [sys.executable, str(EXAMPLE), "--export", str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert retry.returncode != 0 and "refusing to overwrite" in retry.stderr
    assert target.read_bytes() == before


def test_example_serves_immutable_schema_matching_real_validation_and_projection():
    smoke = runpy.run_path(str(ROOT / "scripts/smoke_installed_examples.py"))
    with (
        smoke["_serve"](EXAMPLE) as port,
        httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client,
    ):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        document = response.json()
        validate(document)
        operation = document["paths"]["/items/{item_id}"]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        output_schema = operation["responses"]["default"]["content"]["application/json"]["schema"]
        body = {"name": "tea", "price": 3.5}
        Draft202012Validator({**request_schema, "components": document["components"]}).validate(
            body
        )
        assert client.get("/stats").json() == 0
        valid = client.post(
            "/items/7?limit=2",
            json=body,
            headers={"X-Request-ID": "example", "Cookie": "theme=dark"},
        )
        assert valid.status_code == 201
        assert valid.json() == {
            "id": 7,
            "name": "tea",
            "price": 3.5,
            "limit": 2,
            "request_id": "example",
            "theme": "dark",
        }
        Draft202012Validator({**output_schema, "components": document["components"]}).validate(
            valid.json()
        )
        assert "server-only" not in valid.text
        assert client.get("/stats").json() == 1
        invalid = client.post("/items/7?limit=bad", json=body, headers={"X-Request-ID": "example"})
        assert invalid.status_code == 422
        assert invalid.json() == {"detail": "query parameter 'limit': invalid"}
        Draft202012Validator({**output_schema, "components": document["components"]}).validate(
            invalid.json()
        )
        assert client.get("/stats").json() == 1
        assert client.get("/openapi.json").content == response.content
