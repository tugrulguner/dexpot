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
        assert "use a source checkout containing\nthis feature" not in text


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


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "ROADMAP.md",
        "CONTRIBUTING.md",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/guides/typed-api.md",
    ],
)
def test_python314_floor_names_the_patch_release(relative: str) -> None:
    text = (ROOT / relative).read_text()
    paragraph = next(p for p in text.split("\n\n") if "msgspec>=0.20" in p)
    assert "0.9.1" in paragraph
    assert "msgspec>=0.19" in paragraph
    assert "not yet released" not in paragraph
    assert "dependency correction (unreleased)" not in paragraph


@pytest.mark.parametrize("relative", ["examples/outbound_io.py", "examples/database.py"])
def test_patch_example_workflows_name_availability(relative: str) -> None:
    assert "0.9.1 or newer" in (ROOT / relative).read_text()


def test_patch_release_records_all_consumed_fragments() -> None:
    import re

    changelog = (ROOT / "CHANGELOG.md").read_text()
    section = re.search(r"^## \[0\.9\.1\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    assert section is not None
    for phrase in (
        "bounded outbound blocking-HTTP example",
        "retry-safe SQLite creation",
        "msgspec 0.20 or newer",
        "bounded write-gate rejection",
        "pinned Playwright container",
        "without claiming a stable speedup",
    ):
        assert phrase in section.group(1)


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "ROADMAP.md",
        "CONTRIBUTING.md",
        "examples/README.md",
        "examples/decoded_query.py",
        "examples/repeated_query.py",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/route-contract.md",
        "website/src/content/docs/guides/typed-api.md",
    ],
)
def test_query_consumers_name_the_minimum_release(relative: str) -> None:
    assert "0.10.0" in (ROOT / relative).read_text()


def test_query_release_records_all_consumed_fragments() -> None:
    import re

    changelog = (ROOT / "CHANGELOG.md").read_text()
    section = re.search(r"^## \[0\.10\.0\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    assert section is not None
    for phrase in ("repeated query", "Request.query_pairs()", "benchmark calibration check"):
        assert phrase in section.group(1)


@pytest.mark.parametrize(
    ("relative", "marker"),
    [
        ("README.md", "`request.cookie_pairs()` parses"),
        ("README.md", "`request.peer`, the direct TCP peer"),
        ("ROADMAP.md", "parsed cookie pairs.**"),
        ("ROADMAP.md", "direct socket peer.**"),
        ("examples/README.md", "examples/cookie_preferences.py`"),
        ("examples/README.md", "examples/request_peer.py`"),
        ("examples/cookie_preferences.py", '"""Read a display preference'),
        ("examples/request_peer.py", '"""Inspect a direct connection'),
        ("src/dexpot/templates/skills/dexpot.md", "`request.cookie_pairs()` parses"),
        ("src/dexpot/templates/skills/dexpot.md", "`request.peer` is the direct TCP"),
        ("website/src/content/docs/route-contract.md", "`request.cookie_pairs()` parses"),
        ("website/src/content/docs/route-contract.md", "`request.peer` is the direct TCP"),
        ("website/src/content/docs/guides/typed-api.md", "[parsed cookie pairs]"),
        ("website/src/content/docs/guides/typed-api.md", "[direct socket peer]"),
    ],
)
def test_request_metadata_consumers_name_the_minimum_release(relative: str, marker: str) -> None:
    text = (ROOT / relative).read_text()
    paragraph = next(p for p in text.split("\n\n") if marker in p and not p.startswith("|"))
    assert "0.11.0" in paragraph
    assert "development checkout" not in paragraph
    assert "Not available" not in paragraph


def test_request_metadata_release_notes_and_links() -> None:
    import re
    import tomllib

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = tuple(map(int, metadata["project"]["version"].split(".")))
    assert version >= (0, 11, 0)
    changelog = (ROOT / "CHANGELOG.md").read_text()
    sections = re.findall(r"^## \[0\.11\.0\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    assert len(sections) == 1
    assert all(name in sections[0] for name in ("Request.cookie_pairs()", "Request.peer"))
    route = (ROOT / "website/src/content/docs/route-contract.md").read_text()
    typed = (ROOT / "website/src/content/docs/guides/typed-api.md").read_text()
    for slug, title in (
        ("parsed-cookie-pairs", "Parsed cookie pairs"),
        ("direct-socket-peer", "Direct socket peer"),
    ):
        assert f'\n<span id="{slug}-development-checkout"></span>\n\n### {title}\n' in route
        assert f"(/route-contract/#{slug})" in typed
