"""Executable consistency checks for public documentation and CLI surfaces."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

import dexpot
from dexpot.cli import app

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
runner = CliRunner()


def test_readme_python_blocks_compile() -> None:
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(), re.DOTALL)

    assert len(blocks) >= 3
    for index, block in enumerate(blocks, 1):
        compile(block, f"README:{index}", "exec")


def test_readme_relative_markdown_links_exist() -> None:
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", README.read_text())
    missing = []
    for target in links:
        if "://" in target or target.startswith("#"):
            continue
        path = ROOT / target.split("#", 1)[0]
        if not path.exists():
            missing.append(target)

    assert missing == []


def test_public_names_documented_by_quick_start_are_importable() -> None:
    assert dexpot.Dex is not None
    assert isinstance(dexpot.__version__, str)


def test_cli_exposes_documented_topology() -> None:
    help_result = runner.invoke(app, ["--help"])
    add_result = runner.invoke(app, ["add", "--help"])
    skills_result = runner.invoke(app, ["add", "skills", "--help"], color=True)

    assert help_result.exit_code == 0
    assert "serve" in help_result.output
    assert "add" in help_result.output
    assert "version" in help_result.output
    assert add_result.exit_code == 0
    assert "skills" in add_result.output
    assert skills_result.exit_code == 0
    skills_output = re.sub(r"\x1b\[[0-9;]*m", "", skills_result.output)
    assert "--agent" in skills_output
    assert "--path" in skills_output


def test_both_version_surfaces_derive_from_package_metadata() -> None:
    option = runner.invoke(app, ["--version"])
    command = runner.invoke(app, ["version"])

    assert option.exit_code == 0
    assert command.exit_code == 0
    assert option.output.strip() == f"dexpot {dexpot.__version__}"
    assert command.output.strip() == f"dexpot {dexpot.__version__}"


def test_readme_does_not_claim_unshipped_framework_features() -> None:
    text = " ".join(README.read_text().split())

    assert "not yet recommended for untrusted production traffic" in text
    assert "does not yet enforce the returned type" in text
    assert "are not yet injectable" in text


def test_readme_uses_pypi_install_for_the_release() -> None:
    text = README.read_text()

    assert 'pip install "dexpot[cli]"' in text
    assert "img.shields.io/pypi/v/dexpot" in text
    assert "git+https://github.com/tugrulguner/dexpot.git" not in text
