"""Verify the native sdist contains source and excludes local build state."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    with tarfile.open(args.archive) as archive:
        names = archive.getnames()
    forbidden = [
        name for name in names if any(part in name for part in ("/dist", "/target", "/.venv"))
    ]
    assert forbidden == [], forbidden
    for suffix in (
        "/Cargo.lock",
        "/Cargo.toml",
        "/LICENSE",
        "/README.md",
        "/pyproject.toml",
        "/python/dexpot_native/__init__.py",
        "/python/dexpot_native/_parser.pyi",
        "/python/dexpot_native/py.typed",
        "/src/lib.rs",
    ):
        assert any(name.endswith(suffix) for name in names), suffix
    print(f"verified clean native sdist: {args.archive}")


if __name__ == "__main__":
    main()
