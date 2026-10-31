"""Keep the path-annotation boundary synchronized without claiming a released fix."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CONTRIBUTING.md",
        "examples/README.md",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/route-contract.md",
        "website/src/content/docs/guides/typed-api.md",
    ],
)
def test_path_annotation_contract_is_explicit_and_unreleased(relative: str) -> None:
    text = (ROOT / relative).read_text()
    assert "Path annotations support only `str`, `int`, unannotated parameters, and `Any`." in text
    assert (
        "`float`, `bool`, `Enum`, `Annotated`, unions, and explicit `None` are unsupported." in text
    )
    assert "Unreleased correction:" in text
    assert "`TypeError` during registration" in text
