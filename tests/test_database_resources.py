from __future__ import annotations

import contextlib
import runpy
import socket
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples/database.py"


def test_partial_pool_open_failure_closes_previously_opened_connection(tmp_path, monkeypatch):
    module = runpy.run_path(str(EXAMPLE))
    connect = sqlite3.connect
    opened = []

    def fail_second(*args, **kwargs):
        if opened:
            raise OSError("second database connection unavailable")
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", fail_second)
    with pytest.raises(OSError, match="second database"):
        module["SQLitePool"](str(tmp_path / "partial.db"), 2)
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


@contextlib.contextmanager
def _running(app):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    errors = []

    def serve():
        try:
            app.serve("127.0.0.1", port)
        except BaseException as error:
            errors.append(error)

    server = threading.Thread(target=serve)
    server.start()
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                assert not errors, errors
                assert time.monotonic() < deadline
                time.sleep(0.01)
        yield f"http://127.0.0.1:{port}", server
    finally:
        app._stopping.set()
        server.join(timeout=5)
        assert not server.is_alive()
        assert not errors, errors


def test_concurrent_http_handlers_exclusively_lease_distinct_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("DEXPOT_WORKERS", "1")
    monkeypatch.setenv("DEXPOT_EXAMPLE_DB", str(tmp_path / "concurrent.db"))
    monkeypatch.setenv("DEXPOT_EXAMPLE_POOL_SIZE", "2")
    module = runpy.run_path(str(EXAMPLE))
    app = module["app"]
    barrier = threading.Barrier(2, timeout=3)
    leased = []
    lock = threading.Lock()

    @app.get("/concurrent")
    def concurrent():
        with module["_pool"]().lease() as connection:
            with lock:
                leased.append(id(connection))
            barrier.wait()
            # Both leases are held concurrently above; SQLite still has one writer.
            # Serialize only the test writes, not pool acquisition or the barrier.
            with lock, connection:
                connection.execute(
                    "INSERT INTO items(name,price) VALUES (?,?)", ("concurrent", 1.0)
                )
            return {"ok": True}

    with _running(app) as (base, _):
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(lambda _: httpx.get(base + "/concurrent"), range(2)))
        assert [r.status_code for r in replies] == [200, 200]
        assert len(leased) == len(set(leased)) == 2
    with contextlib.closing(sqlite3.connect(tmp_path / "concurrent.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone() == (2,)


def test_held_http_handler_retains_real_database_until_after_drain(tmp_path, monkeypatch):
    monkeypatch.setenv("DEXPOT_WORKERS", "1")
    monkeypatch.setenv("DEXPOT_EXAMPLE_DB", str(tmp_path / "held.db"))
    events = tmp_path / "held.jsonl"
    monkeypatch.setenv("DEXPOT_EXAMPLE_EVENTS", str(events))
    module = runpy.run_path(str(EXAMPLE))
    app = module["app"]
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    checked = []
    connections = []

    @app.get("/held")
    def held():
        try:
            with module["_pool"]().lease() as connection:
                connections.append(connection)
                entered.set()
                assert release.wait(5)
                checked.append(connection.execute("SELECT 7").fetchone())
            return {"ok": True}
        finally:
            finished.set()

    drain = app._lifecycle._begin_drain
    monkeypatch.setattr(app._lifecycle, "_begin_drain", lambda timeout: drain(timeout=0))
    with _running(app) as (base, server):
        port = int(base.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            try:
                client.sendall(b"GET /held HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
                assert entered.wait(3)
                app._stopping.set()
                server.join(timeout=3)
                assert not server.is_alive()
                assert '"close"' not in events.read_text()
                release.set()
                assert finished.wait(3)
                deadline = time.monotonic() + 3
                while '"close"' not in events.read_text():
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert checked == [(7,)]
                with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                    connections[0].execute("SELECT 1")
            finally:
                release.set()
