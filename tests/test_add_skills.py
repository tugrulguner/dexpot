"""Tests for `dexpot add skills`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dexpot.cli import app
from dexpot.commands.add_skills import Agent, detect_agents

runner = CliRunner()

EXPECTED = {
    "claude": ".claude/skills/dexpot/SKILL.md",
    "cursor": ".cursor/rules/dexpot.mdc",
    "windsurf": ".windsurf/rules/dexpot.md",
    "copilot": ".github/copilot-instructions.md",
    "cline": ".clinerules/dexpot.md",
    "codex": "AGENTS.md",
}


@pytest.mark.parametrize(("agent", "relative"), sorted(EXPECTED.items()))
def test_skill_is_written_where_each_agent_reads_it(
    agent: str, relative: str, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["add", "skills", "--agent", agent, "--path", str(tmp_path)])

    assert result.exit_code == 0, result.output
    written = tmp_path / relative
    assert written.is_file()
    text = written.read_text()
    assert "# dexpot applications" in text
    assert "## Route rules" in text


def test_claude_skill_has_discovery_frontmatter(tmp_path: Path) -> None:
    result = runner.invoke(app, ["add", "skills", "--agent", "claude", "--path", str(tmp_path)])

    assert result.exit_code == 0
    text = (tmp_path / ".claude/skills/dexpot/SKILL.md").read_text()
    frontmatter = text.split("---")[1]
    assert text.startswith("---\n")
    assert 'name: "dexpot"' in frontmatter
    assert "description:" in frontmatter


@pytest.mark.parametrize("agent", ["copilot", "codex"])
def test_shared_instruction_files_preserve_project_content(agent: str, tmp_path: Path) -> None:
    relative = EXPECTED[agent]
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Project rules\n\nKeep this.\n")

    result = runner.invoke(app, ["add", "skills", "--agent", agent, "--path", str(tmp_path)])

    assert result.exit_code == 0
    text = path.read_text()
    assert "# Project rules" in text
    assert "Keep this." in text
    assert text.count("dexpot:managed:start") == 1


def test_reinstall_replaces_managed_block(tmp_path: Path) -> None:
    for _ in range(3):
        result = runner.invoke(app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)])
        assert result.exit_code == 0

    text = (tmp_path / "AGENTS.md").read_text()
    assert text.count("dexpot:managed:start") == 1
    assert text.count("dexpot:managed:end") == 1


@pytest.mark.parametrize(
    ("trailing", "expected_tail"),
    [("AFTER", "AFTER"), ("\nAFTER", "AFTER"), ("\r\nAFTER", "AFTER"), ("", "")],
)
def test_reinstall_preserves_content_after_managed_block(
    trailing: str, expected_tail: str, tmp_path: Path
) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("<!-- dexpot:managed:start -->\nold\n<!-- dexpot:managed:end -->" + trailing)

    result = runner.invoke(app, ["add", "skills", "--agent", "codex", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert path.read_text().endswith(expected_tail)


def test_detects_only_unambiguous_existing_configuration(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    (tmp_path / "AGENTS.md").write_text("# Used by many agents\n")
    (tmp_path / ".github").mkdir()

    assert set(detect_agents(tmp_path)) == {Agent.claude, Agent.cursor}


def test_existing_copilot_instruction_is_detected(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "copilot-instructions.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Existing\n")

    assert detect_agents(tmp_path) == [Agent.copilot]


def test_install_without_agent_uses_detected_configuration(tmp_path: Path) -> None:
    (tmp_path / ".clinerules").mkdir()

    result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".clinerules/dexpot.md").is_file()
    assert not (tmp_path / ".claude").exists()


def test_legacy_cline_file_is_preserved_and_updated(tmp_path: Path) -> None:
    path = tmp_path / ".clinerules"
    path.write_text("# Existing Cline rules\n\nKeep this.\n")

    for _ in range(2):
        result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])
        assert result.exit_code == 0, result.output

    text = path.read_text()
    assert "# Existing Cline rules" in text
    assert "Keep this." in text
    assert "# dexpot applications" in text
    assert text.count("dexpot:managed:start") == 1
    assert text.count("dexpot:managed:end") == 1


def test_install_without_detected_agent_lists_explicit_choices(tmp_path: Path) -> None:
    result = runner.invoke(app, ["add", "skills", "--path", str(tmp_path)])

    assert result.exit_code == 1
    assert "--agent" in result.output
    assert "claude" in result.output
    assert "codex" in result.output


def test_install_rejects_non_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    result = runner.invoke(app, ["add", "skills", "--agent", "claude", "--path", str(missing)])

    assert result.exit_code == 1
    assert "not a directory" in result.output
