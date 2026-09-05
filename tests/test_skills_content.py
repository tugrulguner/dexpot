"""Contract checks for dexpot's packaged coding-agent guidance."""

from __future__ import annotations

import re

import pytest

from dexpot.skills.content import SKILL_DESCRIPTION, SKILL_NAME, skill_body


def test_skill_ships_inside_package() -> None:
    assert skill_body().strip()
    assert SKILL_NAME == "dexpot"


def test_description_tells_agents_when_to_load_skill() -> None:
    assert "dexpot" in SKILL_DESCRIPTION
    assert "free-threaded" in SKILL_DESCRIPTION
    assert len(SKILL_DESCRIPTION) < 500


@pytest.mark.parametrize(
    "rule",
    [
        "msgspec",
        "response=",
        "request: Request",
        "Keyword-only",
        "*args",
        "structural shape",
        "Free-threaded",
        "bounded pool",
        "DEXPOT_WORKERS",
        "DEXPOT_HTTP_PARSER",
        "keep-alive connection",
        "SIGINT/SIGTERM",
        "real socket server",
        "wrk",
        "fast 503",
    ],
)
def test_skill_documents_public_and_operational_contract(rule: str) -> None:
    assert rule in skill_body()


def test_skill_documents_current_boundaries() -> None:
    body = skill_body()
    for boundary in (
        "OpenAPI",
        "Chunked request bodies",
        "Query/header injection",
        "does **not** currently validate",
        "internal server error",
        "Structured request IDs",
    ):
        assert boundary in body


def test_skill_documents_current_body_binding_order() -> None:
    body = skill_body()
    assert "first non-path, non-Request parameter is the body parameter" in body
    assert body.index("### Explicit annotation namespaces") < body.index("## HTTP boundary")
    assert "rejects a directly returned Request" in body
    assert "nested Request values" in body
    assert "outside the recursive guard" in body
    assert "default-only parameters after it" in body


def test_skill_documents_native_parser_selection_contract() -> None:
    body = " ".join(skill_body().split())
    assert "defaults to `auto`" in body
    assert "otherwise Python" in body
    assert "`DEXPOT_HTTP_PARSER=python` forces" in body
    assert "`native` requires the extension" in body
    assert "does not own sockets, bodies, handlers, scheduling, or supervision" in body


def test_skill_keeps_downstream_verification_separate_from_maintainer_work() -> None:
    body = skill_body()

    for application_check in (
        "application imports and all routes register",
        "real HTTP success and failure paths pass",
        'getattr(sys, "_is_gil_enabled", lambda: True)()',
    ):
        assert application_check in body

    for maintainer_check in (
        "make check",
        "make build",
        "wheel and sdist",
        "packaged skill content",
        "README and roadmap",
    ):
        assert maintainer_check not in body


def test_skill_python_examples_compile() -> None:
    blocks = re.findall(r"```python\n(.*?)```", skill_body(), re.DOTALL)

    assert blocks
    for index, block in enumerate(blocks, 1):
        compile(block, f"dexpot-skill:{index}", "exec")
