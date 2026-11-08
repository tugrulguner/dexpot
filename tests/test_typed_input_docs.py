"""Keep released scalar-input availability separate from path rules."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CONTRIBUTING.md",
        "ROADMAP.md",
        "examples/README.md",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/route-contract.md",
        "website/src/content/docs/guides/typed-api.md",
    ],
)
def test_scalar_input_consumers_name_the_release(relative: str) -> None:
    text = (ROOT / relative).read_text()
    assert "Included in v0.9.0: typed query/header/cookie inputs." in text
    assert "Unreleased:" not in text
    for marker in ("Query", "Header", "Cookie"):
        assert marker in text
    assert "Annotated" in text
    assert "422" in text
