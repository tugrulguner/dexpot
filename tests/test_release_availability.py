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


def test_roadmap_separates_available_lifecycle_from_future_inputs() -> None:
    text = (ROOT / "ROADMAP.md").read_text()
    assert "**Next application capabilities:** typed input sources and OpenAPI" in text
    assert "**Included in v0.8.0:** `Dex.lifespan(factory)`" in text
    assert "macOS performance remains unqualified" in text


def test_nested_measurements_keep_their_original_provenance() -> None:
    text = (ROOT / "docs/gil-nested-direct-experiment.md").read_text()
    assert "Implementation included in v0.8.0" in text
    assert "historical pre-release evidence" in text
    assert "Both wheel versions are 0.7.1" in text
    assert "registration CPU" in text
