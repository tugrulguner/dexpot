from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
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
def test_openapi_source_availability_and_opt_in_are_explicit(path):
    text = (ROOT / path).read_text()
    assert "Unreleased: OpenAPI export." in text
    assert "Public v0.8.1 does not include Dex.openapi()." in text
    assert "Dex(openapi=True)" in text
    assert "3.1" in text
