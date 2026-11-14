"""Keep supported interpreter/native-codec dependency pairs honest."""

import tomllib
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def _requirements(python: str) -> list[Requirement]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    environment = {
        **default_environment(),
        "python_version": python,
        "python_full_version": python + ".0",
    }
    return [
        requirement
        for text in project["dependencies"]
        if (requirement := Requirement(text)).name == "msgspec"
        and (requirement.marker is None or requirement.marker.evaluate(environment))
    ]


def test_python314_rejects_msgspec_that_loses_struct_fields():
    selected = _requirements("3.14")
    assert selected, "the native codec must remain a declared runtime dependency"
    assert not all("0.19.0" in requirement.specifier for requirement in selected), (
        "Python 3.14 must not resolve msgspec 0.19: ordinary Struct fields disappear"
    )


@pytest.mark.parametrize(
    "python,version,accepted",
    [
        ("3.12", "0.18.6", False),
        ("3.12", "0.19.0", True),
        ("3.13", "0.19.0", True),
        ("3.14", "0.19.0", False),
        ("3.14", "0.20.0", True),
        ("3.14", "0.22.0", True),
    ],
)
def test_native_dependency_floor_preserves_older_python(python, version, accepted):
    selected = _requirements(python)
    assert len(selected) == 1, "exactly one native dependency branch must apply"
    assert all(version in requirement.specifier for requirement in selected) is accepted
