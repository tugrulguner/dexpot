"""Contract tests for dexpot's contributor entry points."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENT_GUIDANCE = ROOT / "AGENTS.md"
CLAUDE_GUIDANCE = ROOT / "CLAUDE.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
REVIEWING = ROOT / "docs" / "reviewing.md"
ISSUE_FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
PULL_REQUEST_TEMPLATE = ROOT / ".github" / "pull_request_template.md"
CHANGELOG_GUIDE = ROOT / "changelog.d" / "README.md"
CHANGELOG_WORKFLOW = ROOT / ".github" / "workflows" / "changelog.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_internal_agent_guidance_points_to_authoritative_maintainer_rules() -> None:
    guidance = _text(AGENT_GUIDANCE)

    assert "maintaining Dexpot itself" in guidance
    assert "CONTRIBUTING.md" in guidance
    assert "docs/reviewing.md" in guidance
    assert "make check" in guidance
    assert "dexpot add skills" in guidance
    assert "downstream" in guidance
    assert "src/dexpot/templates/skills/dexpot.md" in guidance


def test_claude_guidance_is_an_alias_of_cross_agent_guidance() -> None:
    assert CLAUDE_GUIDANCE.is_symlink()
    assert CLAUDE_GUIDANCE.readlink() == Path("AGENTS.md")
    assert _text(CLAUDE_GUIDANCE) == _text(AGENT_GUIDANCE)


def test_bug_form_collects_runtime_and_contributor_context() -> None:
    bug = _text(ISSUE_FORMS / "bug.yml")

    for field in (
        "Current behavior",
        "Expected behavior",
        "Minimal runnable application",
        "Exact reproduction steps and request",
        "Python version",
        "GIL status",
        "Operating system",
        "Contribution intent",
    ):
        assert field in bug
    assert "DEXPOT_POOL" in bug
    assert "removed secrets" in bug


def test_feature_form_collects_problem_contract_scope_and_intent() -> None:
    feature = _text(ISSUE_FORMS / "feature.yml")

    for field in (
        "Problem",
        "What happens now",
        "Why I want it",
        "Concrete use case",
        "Proposed contract",
        "Acceptance criteria",
        "Open question",
        "Implementation notes",
        "Alternatives considered",
        "Scope and non-goals",
        "Contribution intent",
    ):
        assert field in feature
    assert "registration, compiled route, request, scheduler, and response boundaries" in feature


def test_issue_forms_parse_with_unique_ids_and_required_intent() -> None:
    for name in ("bug.yml", "feature.yml"):
        form = yaml.safe_load(_text(ISSUE_FORMS / name))
        fields = [item for item in form["body"] if "id" in item]
        ids = [item["id"] for item in fields]
        intent = next(item for item in fields if item["id"] == "contribution-intent")

        assert ids
        assert len(ids) == len(set(ids))
        assert intent["type"] == "dropdown"
        assert intent["validations"]["required"] is True


def test_pull_request_template_requires_scope_safety_evidence_and_review_help() -> None:
    template = _text(PULL_REQUEST_TEMPLATE)

    for heading in (
        "## Summary and motivation",
        "## Related issue or direct-PR reason",
        "## Scope and non-goals",
        "## Safety and compatibility",
        "## Verification and behavioral evidence",
        "## Documentation and changelog",
        "## Reviewer guidance",
    ):
        assert heading in template
    assert "Closes #<issue-number>" in template
    assert "real HTTP or CLI surface" in template
    assert "GIL and free-threaded" in template
    assert "make check" in template
    assert "make build" in template


def test_contributor_journey_classifies_work_and_prevents_duplicate_claims() -> None:
    contributing = _text(CONTRIBUTING)

    assert "Substantial contract work: open an issue first" in contributing
    assert "Small direct changes" in contributing
    assert "Questions and early ideas" in contributing
    assert "Claimed community work" in contributing
    assert "comment and wait for confirmation" in contributing
    assert "reviewer can reproduce" in contributing


def test_reviewing_pins_exact_head_and_requires_integration_evidence() -> None:
    reviewing = _text(REVIEWING)

    assert "Pin the exact head" in reviewing
    assert "reviewed head SHA" in reviewing
    assert "current main" in reviewing
    assert "green result against an obsolete base" in reviewing


def test_changelog_guidance_is_consistent_across_contributor_surfaces() -> None:
    contributing = _text(CONTRIBUTING)
    template = _text(PULL_REQUEST_TEMPLATE)
    guide = _text(CHANGELOG_GUIDE)
    workflow = _text(CHANGELOG_WORKFLOW)
    config = tomllib.loads(_text(ROOT / "pyproject.toml"))["tool"]["towncrier"]

    for document in (contributing, guide):
        assert "<issue-number>.<type>.md" in document
        assert "towncrier create +.changed.md" in document
    assert "<issue-number>.<type>.md" in template
    assert "+<identifier>.<type>.md" in template
    assert 'select(.status != "removed") | .filename' in workflow
    assert "must use an issue number" in workflow
    assert config["issue_format"].endswith("/issues/{issue})")


def test_contribution_document_links_resolve() -> None:
    documents = (CONTRIBUTING, REVIEWING, CHANGELOG_GUIDE, PULL_REQUEST_TEMPLATE)
    markdown_link = re.compile(r"\[[^]]+\]\(([^)]+)\)")

    for document in documents:
        for target in markdown_link.findall(_text(document)):
            if target.startswith(("http://", "https://", "#")) or "<" in target:
                continue
            path_text = target.split("#", 1)[0]
            if not path_text:
                continue
            assert (document.parent / path_text).resolve().exists(), (
                f"{document.relative_to(ROOT)} links to missing path {target}"
            )
