"""Keep lifecycle availability distinct from historical performance evidence."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "examples/README.md",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/guides/deployment.md",
    ],
)
def test_lifecycle_consumers_name_the_minimum_release(relative: str) -> None:
    text = (ROOT / relative).read_text()
    assert "0.8.0 or newer" in text
    assert "app.lifespan(factory)" in text


def test_roadmap_separates_released_foundations_from_remaining_work() -> None:
    text = (ROOT / "ROADMAP.md").read_text()
    assert "**Next application capabilities:** finish the remaining 3.3 contracts" in text
    assert "Included in v0.9.0: typed query/header/cookie inputs." in text
    assert "Included in v0.9.0: OpenAPI export." in text
    assert "**Included in v0.8.0:** `Dex.lifespan(factory)`" in text
    assert "macOS performance remains unqualified" in text


def test_new_examples_and_guides_name_release_availability() -> None:
    for relative in ("examples/typed_inputs.py", "examples/openapi.py"):
        text = (ROOT / relative).read_text()
        assert "0.9.0 or newer" in text
        assert "unreleased" not in text.lower()
        assert "source-only" not in text.lower()
    for relative in ("README.md", "website/src/content/docs/guides/typed-api.md"):
        text = (ROOT / relative).read_text()
        assert "#typed-input-sources-unreleased" not in text
        assert "#typed-input-sources" in text


def test_boundary_page_describes_released_input_and_export_contracts() -> None:
    text = (ROOT / "website/src/content/docs/current-boundaries.mdx").read_text()
    assert "Included in v0.9.0: typed query/header/cookie inputs." in text
    assert "Included in v0.9.0: OpenAPI export." in text
    assert "Dex(openapi=True)" in text
    assert "no automatic documentation endpoint or UI" in text
    assert "not yet injectable handler parameters" not in text
    assert "no middleware, OpenAPI generation" not in text


def test_nested_measurements_keep_their_original_provenance() -> None:
    text = (ROOT / "docs/gil-nested-direct-experiment.md").read_text()
    assert "Implementation included in v0.8.0" in text
    assert "historical pre-release evidence" in text
    assert "Both wheel versions are 0.7.1" in text
    assert "registration CPU" in text


def test_roadmap_names_the_path_correction_release() -> None:
    text = (ROOT / "ROADMAP.md").read_text()
    assert "**Included in v0.8.1:**" in text
    assert "unsupported path annotations" in text
    assert "integer conversion" in text


def test_patch_changelog_covers_runtime_examples_and_tooling() -> None:
    import re

    changelog = (ROOT / "CHANGELOG.md").read_text()
    section = re.search(r"^## \[0\.8\.1\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    assert section is not None
    text = section.group(1)
    for phrase in (
        "unsupported path parameter annotations",
        "nested checked-response",
        "Python development and website build dependencies",
    ):
        assert phrase in text
