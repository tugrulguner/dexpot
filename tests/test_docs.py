"""Executable consistency checks for public documentation and CLI surfaces."""

from __future__ import annotations

import re
import struct
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from typer.testing import CliRunner

import dexpot
from dexpot.cli import app

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ROADMAP = ROOT / "ROADMAP.md"
HERO = ROOT / "assets" / "dexpot.png"
EXECUTION_DIAGRAM = ROOT / "docs" / "assets" / "dexpot-execution.png"
EXECUTION_DIAGRAM_SOURCE = ROOT / "docs" / "assets" / "dexpot-execution.svg"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
CHANGELOG_GUIDE = ROOT / "changelog.d" / "README.md"
CHANGELOG_WORKFLOW = ROOT / ".github" / "workflows" / "changelog.yml"
ISSUE_FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
PULL_REQUEST_TEMPLATE = ROOT / ".github" / "pull_request_template.md"
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


def test_readme_hero_is_an_optimized_png() -> None:
    data = HERO.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    text = README.read_text()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert (width, height) == (1200, 900)
    assert len(data) < 700_000
    assert (
        'src="https://raw.githubusercontent.com/tugrulguner/dexpot/main/assets/dexpot.png"' in text
    )
    assert 'alt="dexpot synchronous Python API framework"' in text
    assert 'width="600"' in text


def test_readme_execution_diagram_is_rendered_and_editable() -> None:
    data = EXECUTION_DIAGRAM.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    text = README.read_text()
    source = EXECUTION_DIAGRAM_SOURCE.read_text()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert (width, height) == (2400, 1350)
    assert len(data) < 700_000
    assert ET.fromstring(source).tag.endswith("svg")
    assert "ONE ENDPOINT PLAN · TWO RUNTIME PATHS" in source
    assert "Plain Python handlers · msgspec I/O · interpreter-aware scheduling." in source
    assert "FREE-THREADED CPYTHON" in source
    assert "STANDARD GIL CPYTHON" in source
    font_sizes = [int(size) for size in re.findall(r"font-size:\s*(\d+)px", source)]
    assert font_sizes
    assert min(font_sizes) >= 28
    assert "literal + params" in source
    assert "literal / parametric match" not in source
    assert "bound + parse request head" in source
    assert "compatible Rust / PyO3" in source
    assert "Python only if absent" in source
    assert "SAME PYTHON HANDLER" in source
    assert 'x="2235" y="565"' in source
    assert "SAME HANDLER PATH" not in source
    assert "compatible native" not in source
    assert "Python if absent" not in source
    assert "native if installed" not in source
    assert "Python fallback" not in source
    assert (
        'src="https://raw.githubusercontent.com/tugrulguner/dexpot/'
        'main/docs/assets/dexpot-execution.png"' in text
    )
    assert 'width="960"' in text


def test_roadmap_separates_shipped_native_seam_from_promotion_gates() -> None:
    readme = " ".join(README.read_text().split())
    roadmap = ROADMAP.read_text()

    assert "optional native request-head seam" in readme
    assert "Remaining work is organized around four gates" in readme
    assert roadmap.index("### 2. Optional native request-head seam") < roadmap.index(
        "## Next milestones"
    )
    assert "The source subproject and its CI gates are complete" in roadmap
    assert "The accelerator is not yet published" in roadmap
    assert "#### Native parser promotion gates" in roadmap
    assert "#### Optional Rust request-head acceleration" not in roadmap


def test_public_names_documented_by_quick_start_are_importable() -> None:
    assert dexpot.Dex is not None
    assert isinstance(dexpot.__version__, str)


def test_typed_package_ships_pep561_marker() -> None:
    marker = Path(dexpot.__file__).with_name("py.typed")
    assert marker.is_file()


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
    source = README.read_text()
    text = " ".join(source.split())

    assert "not yet recommended for untrusted production traffic" in text
    assert source.index("alpha software") < source.index("## Quick start")
    assert "does not yet enforce the returned type" in text
    assert "are not yet injectable" in text


def test_contributor_entry_points_are_actionable() -> None:
    readme = README.read_text()
    contributing = CONTRIBUTING.read_text()
    pull_request_template = PULL_REQUEST_TEMPLATE.read_text()

    assert "issues/new/choose" in readme
    assert "github.com/tugrulguner/dexpot/discussions" in readme
    assert "github.com/tugrulguner/dexpot" in readme
    assert 'href="#community"' in readme
    normalized_readme = " ".join(readme.split())
    assert readme.count("https://discord.gg/u3AANZr6RG") >= 3
    assert "shared community for dexpot, intpot, summonpot" in normalized_readme
    assert "Use GitHub [issues]" in normalized_readme
    assert "and Discord for exploratory design" in normalized_readme
    assert "issues/new?template=bug.yml" in contributing
    assert "issues/new?template=feature.yml" in contributing
    assert "Closes #<issue-number>" in contributing
    assert "Closes #" in pull_request_template
    assert "make check" in pull_request_template
    assert "make build" in pull_request_template
    assert "## Support dexpot" in readme
    assert "use the Star control" in readme


def test_issue_forms_and_template_chooser_are_present() -> None:
    bug = (ISSUE_FORMS / "bug.yml").read_text()
    feature = (ISSUE_FORMS / "feature.yml").read_text()
    chooser = (ISSUE_FORMS / "config.yml").read_text()

    assert 'name: "Bug report"' in bug
    assert "Python version" in bug
    assert "GIL status" in bug
    assert "Minimal runnable application" in bug
    assert 'name: "Feature request"' in feature
    assert "Problem" in feature
    assert "Proposed contract" in feature
    assert "blank_issues_enabled: false" in chooser
    assert "/discussions" in chooser


def test_changelog_fragments_do_not_require_a_pr_number() -> None:
    contributing = CONTRIBUTING.read_text()
    guide = CHANGELOG_GUIDE.read_text()
    workflow = CHANGELOG_WORKFLOW.read_text()
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["towncrier"]

    assert "<issue-number>.<type>.md" in contributing
    assert "towncrier create +.changed.md" in contributing
    assert "<issue-number>.<type>.md" in guide
    assert "\\+[A-Za-z0-9]" in workflow
    assert 'select(.status != "removed") | .filename' in workflow
    assert "issues: read" in workflow
    assert "issues/${issue_number}" in workflow
    assert "must use an issue number" in workflow
    assert "pull/{issue}" not in config["issue_format"]
    assert config["issue_format"].endswith("/issues/{issue})")


def test_readme_uses_pypi_install_for_the_release() -> None:
    text = README.read_text()

    assert 'pip install "dexpot[cli]"' in text
    assert "img.shields.io/pypi/v/dexpot" in text
    assert "git+https://github.com/tugrulguner/dexpot.git" not in text
