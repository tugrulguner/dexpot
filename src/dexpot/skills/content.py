"""Skill content and per-agent formatting."""

from __future__ import annotations

import json
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "templates" / "skills"

SKILL_NAME = "dexpot"
SKILL_TITLE = "dexpot applications"
SKILL_DESCRIPTION = (
    "Build and review synchronous dexpot APIs with compiled routes, msgspec bodies, "
    "bounded HTTP parsing, adaptive GIL/free-threaded scheduling, and real socket tests."
)


def skill_body() -> str:
    """Return the public dexpot framework skill."""
    return (_SKILLS_DIR / "dexpot.md").read_text()


def claude_skill(body: str, *, name: str, description: str) -> str:
    """Format as a discoverable Claude Code skill."""
    return f"---\nname: {json.dumps(name)}\ndescription: {json.dumps(description)}\n---\n\n{body}"


def cursor_rule(body: str, *, description: str) -> str:
    """Format as a model-selected Cursor rule."""
    return f"---\ndescription: {json.dumps(description)}\nalwaysApply: false\n---\n\n{body}"


def windsurf_rule(body: str, *, description: str) -> str:
    """Format as a model-decision Windsurf rule."""
    return f"---\ntrigger: model_decision\ndescription: {json.dumps(description)}\n---\n\n{body}"


def copilot_instruction(body: str) -> str:
    """Format for GitHub Copilot instructions."""
    return body


def cline_rule(body: str) -> str:
    """Format as a Cline rule."""
    return body


def codex_instruction(body: str) -> str:
    """Format for OpenAI Codex CLI instructions."""
    return body
