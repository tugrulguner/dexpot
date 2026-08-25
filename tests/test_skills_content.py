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
        "Keyword-only",
        "*args",
        "structural shape",
        "Free-threaded",
        "bounded pool",
        "DEXPOT_WORKERS",
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
        "exception names and messages",
    ):
        assert boundary in body


def test_skill_python_examples_compile() -> None:
    blocks = re.findall(r"```python\n(.*?)```", skill_body(), re.DOTALL)

    assert blocks
    for index, block in enumerate(blocks, 1):
        compile(block, f"dexpot-skill:{index}", "exec")
