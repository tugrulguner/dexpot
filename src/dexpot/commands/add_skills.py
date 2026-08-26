"""Install dexpot guidance into coding-agent configuration."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import typer

from dexpot.skills.content import (
    SKILL_DESCRIPTION,
    SKILL_NAME,
    claude_skill,
    cline_rule,
    codex_instruction,
    copilot_instruction,
    cursor_rule,
    skill_body,
    windsurf_rule,
)

_MANAGED_START = "<!-- dexpot:managed:start -->"
_MANAGED_END = "<!-- dexpot:managed:end -->"


class Agent(StrEnum):
    """Coding agents dexpot can install guidance for."""

    claude = "claude"
    cursor = "cursor"
    windsurf = "windsurf"
    copilot = "copilot"
    cline = "cline"
    codex = "codex"


def _write_claude(root: Path) -> list[Path]:
    directory = root / ".claude" / "skills" / SKILL_NAME
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(claude_skill(skill_body(), name=SKILL_NAME, description=SKILL_DESCRIPTION))
    return [path]


def _write_cursor(root: Path) -> list[Path]:
    directory = root / ".cursor" / "rules"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SKILL_NAME}.mdc"
    path.write_text(cursor_rule(skill_body(), description=SKILL_DESCRIPTION))
    return [path]


def _write_windsurf(root: Path) -> list[Path]:
    directory = root / ".windsurf" / "rules"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SKILL_NAME}.md"
    path.write_text(windsurf_rule(skill_body(), description=SKILL_DESCRIPTION))
    return [path]


def _write_copilot(root: Path) -> list[Path]:
    path = root / ".github" / "copilot-instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    _upsert_managed_block(path, copilot_instruction(skill_body()))
    return [path]


def _write_cline(root: Path) -> list[Path]:
    directory = root / ".clinerules"
    if directory.is_file():
        _upsert_managed_block(directory, cline_rule(skill_body()))
        return [directory]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SKILL_NAME}.md"
    path.write_text(cline_rule(skill_body()))
    return [path]


def _write_codex(root: Path) -> list[Path]:
    path = root / "AGENTS.md"
    _upsert_managed_block(path, codex_instruction(skill_body()))
    return [path]


def _upsert_managed_block(path: Path, content: str) -> None:
    """Replace dexpot's fenced block while preserving project-owned content."""
    block = f"{_MANAGED_START}\n{content.rstrip()}\n{_MANAGED_END}\n"
    existing = path.read_text() if path.exists() else ""
    start = existing.find(_MANAGED_START)
    end = existing.find(_MANAGED_END)

    if start != -1 and end != -1 and end > start:
        after = end + len(_MANAGED_END)
        for ending in ("\r\n", "\n"):
            if existing.startswith(ending, after):
                after += len(ending)
                break
        updated = existing[:start] + block + existing[after:]
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block
    else:
        updated = block

    path.write_text(updated)


_WRITERS: dict[Agent, Callable[[Path], list[Path]]] = {
    Agent.claude: _write_claude,
    Agent.cursor: _write_cursor,
    Agent.windsurf: _write_windsurf,
    Agent.copilot: _write_copilot,
    Agent.cline: _write_cline,
    Agent.codex: _write_codex,
}

_MARKERS: dict[Agent, tuple[str, ...]] = {
    Agent.claude: (".claude",),
    Agent.cursor: (".cursor",),
    Agent.windsurf: (".windsurf",),
    Agent.copilot: (".github/copilot-instructions.md",),
    Agent.cline: (".clinerules",),
    # AGENTS.md is too widely used to prove Codex is configured, so Codex remains
    # explicit-only and is never auto-detected.
    Agent.codex: (),
}


def detect_agents(root: Path) -> list[Agent]:
    """Return agents with an existing, unambiguous project marker."""
    return [
        agent
        for agent, markers in _MARKERS.items()
        if markers and any((root / marker).exists() for marker in markers)
    ]


def add_skills(
    agent: Agent | None = typer.Option(
        None,
        "--agent",
        help="Install for one agent. Defaults to configured agents detected here.",
    ),
    path: Path = typer.Option(
        Path("."),
        "--path",
        help="Project directory to install into.",
    ),
) -> None:
    """Install dexpot's public framework guidance for a coding agent."""
    root = path.resolve()
    if not root.is_dir():
        typer.echo(f"Error: not a directory: {root}", err=True)
        raise typer.Exit(1)

    if agent is not None:
        targets = [agent]
    else:
        targets = detect_agents(root)
        if not targets:
            typer.echo(
                "No agent configuration found here. Pass --agent to choose one of: "
                + ", ".join(item.value for item in Agent),
                err=True,
            )
            raise typer.Exit(1)

    for target in targets:
        for written in _WRITERS[target](root):
            typer.echo(f"{target.value}: {written.relative_to(root)}")
