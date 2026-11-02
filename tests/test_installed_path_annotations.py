"""Keep installed-distribution acceptance exercising path annotation rejection."""

import runpy
from pathlib import Path


def test_installed_smoke_checks_path_annotation_registration() -> None:
    root = Path(__file__).resolve().parent.parent
    namespace = runpy.run_path(str(root / "scripts" / "smoke_installed_examples.py"))
    namespace["_check_path_annotations"]()
