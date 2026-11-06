from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "database.py"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _serve(tmp_path: Path, pool_size: int = 2) -> Iterator[tuple[str, Path, Path]]:
    port = _port()
    database = tmp_path / "items.sqlite3"
    events = tmp_path / "events.jsonl"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", ""),
            "DEXPOT_EXAMPLE_HOST": "127.0.0.1",
            "DEXPOT_EXAMPLE_PORT": str(port),
            "DEXPOT_EXAMPLE_DB": str(database),
            "DEXPOT_EXAMPLE_POOL_SIZE": str(pool_size),
            "DEXPOT_EXAMPLE_EVENTS": str(events),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out, err = process.communicate()
            raise RuntimeError(f"example exited: {out!r} {err!r}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        out, err = process.communicate()
        raise TimeoutError(f"example startup timeout: {out!r} {err!r}")
    try:
        yield f"http://127.0.0.1:{port}", database, events
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        assert process.returncode == 0


def _events(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [json.loads(line)["event"] for line in path.read_text().splitlines()]


def test_database_example_exists_as_a_runnable_public_file() -> None:
    assert EXAMPLE.is_file(), "examples/database.py must be a runnable example"
    compile(EXAMPLE.read_text(), str(EXAMPLE), "exec")


def test_real_http_write_read_and_durable_sqlite_rows(tmp_path: Path) -> None:
    with _serve(tmp_path) as (base, database, events):
        created = httpx.post(f"{base}/items", json={"name": "keyboard", "price": 19.5})
        assert created.status_code == 201
        item_id = created.json()["id"]
        assert httpx.get(f"{base}/items/{item_id}").json() == {
            "id": item_id,
            "name": "keyboard",
            "price": 19.5,
        }
        assert httpx.get(f"{base}/health").json() == {"ok": True}
    import sqlite3

    with contextlib.closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT name, price FROM items").fetchall() == [
            ("keyboard", 19.5)
        ]
    trace = _events(events)
    assert "commit" in trace and "release" in trace and "close" in trace


def test_invalid_typed_body_does_not_lease_or_mutate(tmp_path: Path) -> None:
    with _serve(tmp_path) as (base, database, events):
        before = _events(events).count("acquire")
        rejected = httpx.post(f"{base}/items", json={"name": 4, "price": 9.0})
        assert rejected.status_code == 422
        assert _events(events).count("acquire") == before
        import sqlite3

        with contextlib.closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)


def test_explicit_rollback_returns_409_and_releases_lease(tmp_path: Path) -> None:
    with _serve(tmp_path) as (base, database, events):
        response = httpx.post(f"{base}/rollback", json={"name": "discard", "price": 1.0})
        assert response.status_code == 409
        assert httpx.post(f"{base}/items", json={"name": "kept", "price": 2.0}).status_code == 201
        import sqlite3

        with contextlib.closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT name FROM items").fetchall() == [("kept",)]
    trace = _events(events)
    assert "rollback" in trace and trace.count("acquire") == trace.count("release")


def test_checked_output_failure_does_not_undo_committed_write(tmp_path: Path) -> None:
    with _serve(tmp_path) as (base, database, events):
        response = httpx.post(f"{base}/encoding-failure", json={"name": "committed", "price": 3.0})
        assert response.status_code == 500
        assert httpx.post(f"{base}/items", json={"name": "after", "price": 4.0}).status_code == 201
        import sqlite3

        with contextlib.closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT name FROM items ORDER BY id").fetchall() == [
                ("committed",),
                ("after",),
            ]
    assert "commit" in _events(events)


def test_pool_exhaustion_is_immediate_503_and_leases_are_bounded(tmp_path: Path) -> None:
    with _serve(tmp_path, pool_size=1) as (base, _database, events):
        with ThreadPoolExecutor(max_workers=1) as executor:
            held = executor.submit(httpx.post, f"{base}/hold", json={"name": "held", "price": 1.0})
            deadline = time.monotonic() + 2
            while _events(events).count("acquire") == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert (
                httpx.post(f"{base}/items", json={"name": "shed", "price": 2.0}).status_code == 503
            )
            assert held.result(timeout=3).status_code == 201
        assert _events(events).count("acquire") == _events(events).count("release")


def test_committed_file_survives_server_restart(tmp_path: Path) -> None:
    database = tmp_path / "persistent.sqlite3"
    first_events = tmp_path / "first.jsonl"
    with _serve_database_at(database, first_events) as base:
        created = httpx.post(f"{base}/items", json={"name": "durable", "price": 7.0})
        assert created.status_code == 201
        item_id = created.json()["id"]
    with _serve_database_at(database, tmp_path / "second.jsonl") as base:
        assert httpx.get(f"{base}/items/{item_id}").json() == {
            "id": item_id,
            "name": "durable",
            "price": 7.0,
        }


@contextlib.contextmanager
def _serve_database_at(database: Path, events: Path) -> Iterator[str]:
    port = _port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", ""),
            "DEXPOT_EXAMPLE_HOST": "127.0.0.1",
            "DEXPOT_EXAMPLE_PORT": str(port),
            "DEXPOT_EXAMPLE_DB": str(database),
            "DEXPOT_EXAMPLE_POOL_SIZE": "2",
            "DEXPOT_EXAMPLE_EVENTS": str(events),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out, err = process.communicate()
            raise RuntimeError(f"example exited: {out!r} {err!r}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        out, err = process.communicate()
        raise TimeoutError(f"example startup timeout: {out!r} {err!r}")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        assert process.returncode == 0


def test_invalid_pool_size_fails_before_database_allocation(tmp_path: Path) -> None:
    port = _port()
    database = tmp_path / "should-not-exist.sqlite3"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "DEXPOT_EXAMPLE_HOST": "127.0.0.1",
            "DEXPOT_EXAMPLE_PORT": str(port),
            "DEXPOT_EXAMPLE_DB": str(database),
            "DEXPOT_EXAMPLE_POOL_SIZE": "0",
        }
    )
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)], cwd=ROOT, env=env, capture_output=True, timeout=8
    )
    assert result.returncode != 0
    assert not database.exists()
