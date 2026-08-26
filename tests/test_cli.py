"""CLI behavior through Typer's public runner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dexpot.cli import app

runner = CliRunner()


def test_serve_rejects_malformed_target() -> None:
    result = runner.invoke(app, ["serve", "main"])

    assert result.exit_code == 1
    assert "module:attribute" in result.output


def test_serve_reports_missing_module_without_traceback() -> None:
    result = runner.invoke(app, ["serve", "module_that_does_not_exist:app"])

    assert result.exit_code == 1
    assert "Error importing" in result.output
    assert "Traceback" not in result.output


def test_serve_reports_missing_attribute(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "sample_app.py").write_text("value = 1\n")
    monkeypatch.syspath_prepend(tmp_path)

    result = runner.invoke(app, ["serve", "sample_app:app"])

    assert result.exit_code == 1
    assert "has no attribute" in result.output


def test_serve_rejects_object_without_serve(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "not_dex.py").write_text("app = object()\n")
    monkeypatch.syspath_prepend(tmp_path)

    result = runner.invoke(app, ["serve", "not_dex:app"])

    assert result.exit_code == 1
    assert "expected a dexpot Dex instance" in result.output
