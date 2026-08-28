"""Parser backend selection is explicit, deterministic, and fail-visible."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _native_available() -> bool:
    try:
        return importlib.util.find_spec("dexpot_native._parser") is not None
    except ModuleNotFoundError:
        return False


def _probe(
    mode: str | None,
    *,
    extra_pythonpath: Path | None = None,
    block_native: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    paths = [str(ROOT / "src")]
    if extra_pythonpath is not None:
        paths.insert(0, str(extra_pythonpath))
    env["PYTHONPATH"] = os.pathsep.join(paths)
    if mode is None:
        env.pop("DEXPOT_HTTP_PARSER", None)
    else:
        env["DEXPOT_HTTP_PARSER"] = mode
    prelude = ""
    if block_native:
        prelude = """
import importlib.abc
import sys
class BlockNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "dexpot_native":
            error = ModuleNotFoundError("No module named 'dexpot_native'")
            error.name = "dexpot_native"
            raise error
        return None
sys.meta_path.insert(0, BlockNative())
"""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            prelude + "\nfrom dexpot._http import PARSER_BACKEND; print(PARSER_BACKEND)",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_default_falls_back_to_python_when_native_is_absent() -> None:
    result = _probe(None, block_native=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "python"


def test_default_selects_a_compatible_native_package(tmp_path: Path) -> None:
    package = tmp_path / "dexpot_native"
    package.mkdir()
    (package / "__init__.py").write_text("PARSER_API_VERSION = 1\n")
    (package / "_parser.py").write_text("def parse_head(*args): return args\n")

    result = _probe(None, extra_pythonpath=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "native"


def test_python_backend_can_be_forced() -> None:
    result = _probe("python")
    assert result.returncode == 0
    assert result.stdout.strip() == "python"


def test_auto_falls_back_when_native_is_absent() -> None:
    result = _probe("auto", block_native=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "python"


def test_explicit_auto_selects_a_compatible_native_package(tmp_path: Path) -> None:
    package = tmp_path / "dexpot_native"
    package.mkdir()
    (package / "__init__.py").write_text("PARSER_API_VERSION = 1\n")
    (package / "_parser.py").write_text("def parse_head(*args): return args\n")

    result = _probe("auto", extra_pythonpath=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "native"


def test_forced_native_is_selected_or_fails_clearly_when_absent() -> None:
    result = _probe("native", block_native=True)
    assert result.returncode != 0
    assert "dexpot-native is not installed" in result.stderr


def test_unknown_backend_is_rejected() -> None:
    result = _probe("surprise")
    assert result.returncode != 0
    assert "DEXPOT_HTTP_PARSER must be one of" in result.stderr


def test_auto_does_not_hide_broken_native_imports(tmp_path: Path) -> None:
    package = tmp_path / "dexpot_native"
    package.mkdir()
    (package / "__init__.py").write_text("from . import _parser\n")
    (package / "_parser.py").write_text("import missing_native_dependency\n")

    result = _probe("auto", extra_pythonpath=tmp_path)
    assert result.returncode != 0
    assert "missing_native_dependency" in result.stderr


def test_incompatible_native_parser_api_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "dexpot_native"
    package.mkdir()
    (package / "__init__.py").write_text("PARSER_API_VERSION = 999\n")
    (package / "_parser.py").write_text("def parse_head(*args): return args\n")

    result = _probe("auto", extra_pythonpath=tmp_path)
    assert result.returncode != 0
    assert "incompatible dexpot-native parser API" in result.stderr


def test_native_backend_preserves_unbounded_python_limit_semantics() -> None:
    if not _native_available():
        pytest.skip("native parser is not installed")

    from dexpot._http import PARSER_BACKEND, HttpLimits, _parse_head

    if PARSER_BACKEND != "native":
        pytest.skip("native parser is not selected")
    huge = 10**100
    limits = HttpLimits(
        request_line_bytes=huge,
        header_bytes=huge + 1,
        header_count=huge,
        body_bytes=huge,
    )
    assert _parse_head(b"GET / HTTP/1.1\r\nHost: example.com", limits)[0] == "GET"
