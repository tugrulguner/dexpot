from __future__ import annotations

import contextlib
import runpy
import sqlite3
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples/database.py"


@pytest.mark.parametrize("path", ["", ":memory:"])
def test_private_sqlite_storage_is_rejected_before_any_connection(path, monkeypatch):
    module = runpy.run_path(str(EXAMPLE))
    connect = sqlite3.connect
    opened = []

    def observe(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observe)
    with (
        pytest.raises(ValueError, match="on-disk"),
        contextlib.closing(module["SQLitePool"](path, 2)),
    ):
        pass
    assert opened == []
