from __future__ import annotations

import contextlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples/database.py"


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def server(
    tmp_path: Path, database: Path | None = None, *, hold_retry_lock: bool = False
) -> Iterator[tuple[str, Path, Path]]:
    db = database or tmp_path / "items.sqlite3"
    events = tmp_path / f"events-{time.time_ns()}.jsonl"
    p = port()
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", ""),
        DEXPOT_EXAMPLE_HOST="127.0.0.1",
        DEXPOT_EXAMPLE_PORT=str(p),
        DEXPOT_EXAMPLE_DB=str(db),
        DEXPOT_EXAMPLE_POOL_SIZE="4",
        DEXPOT_EXAMPLE_EVENTS=str(events),
    )
    command = [sys.executable, str(EXAMPLE)]
    if hold_retry_lock:
        wrapper = (
            "import runpy, os; namespace=runpy.run_path(" + repr(str(EXAMPLE)) + "); "
            "app=namespace['app']; lock=namespace['_retry_lock']; lock.acquire()\n"
            "@app.get('/release-write-gate')\n"
            "def release():\n    lock.release()\n    return {'released': True}\n"
            "app.serve(host='127.0.0.1',port=int(os.environ['DEXPOT_EXAMPLE_PORT']))"
        )
        command = [sys.executable, "-c", wrapper]
    proc = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited: {proc.communicate()!r}")
        try:
            with socket.create_connection(("127.0.0.1", p), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        proc.kill()
        proc.wait(timeout=2)
        raise TimeoutError("server startup timed out")
    try:
        yield f"http://127.0.0.1:{p}", db, events
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        assert proc.returncode == 0


def count_rows(db: Path, table: str) -> int:
    with contextlib.closing(sqlite3.connect(db)) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_busy_retry_write_gate_returns_503_without_leasing(tmp_path: Path) -> None:
    with server(tmp_path, hold_retry_lock=True) as (base, db, events):
        observed = None
        try:
            with contextlib.suppress(httpx.ReadTimeout):
                observed = httpx.post(
                    f"{base}/retry-safe/items",
                    json={"operation_id": "bounded", "name": "x", "price": 1.0},
                    timeout=0.8,
                )
            assert not events.exists() or '"event": "acquire"' not in events.read_text()
        finally:
            assert httpx.get(f"{base}/release-write-gate", timeout=3).status_code == 200
        assert observed is not None, "held write gate must reject, not wait indefinitely"
        assert observed.status_code == 503
        assert observed.json() == {"detail": "retry write busy"}
        assert count_rows(db, "items") == count_rows(db, "operations") == 0


def test_retry_after_checked_reply_failure_replays_committed_result(tmp_path: Path) -> None:
    with server(tmp_path) as (base, db, _events):
        headers = {"X-Demo-Fail-Reply": "1"}
        body = {"operation_id": "op-1", "name": "pen", "price": 2.5}
        first = httpx.post(f"{base}/retry-safe/items", json=body, headers=headers)
        assert first.status_code == 500
        assert count_rows(db, "items") == count_rows(db, "operations") == 1
        retry = httpx.post(f"{base}/retry-safe/items", json=body, headers=headers)
        assert retry.status_code == 201
        assert retry.json() == {"id": 1, "name": "pen", "price": 2.5}
        again = httpx.post(f"{base}/retry-safe/items", json=body)
        assert again.status_code == 201 and again.json() == retry.json()
        assert count_rows(db, "items") == count_rows(db, "operations") == 1
        assert httpx.get(f"{base}/items/1").json() == retry.json()


def test_same_operation_id_with_different_payload_conflicts(tmp_path: Path) -> None:
    with server(tmp_path) as (base, db, _events):
        first = httpx.post(
            f"{base}/retry-safe/items", json={"operation_id": "same", "name": "one", "price": 1.0}
        )
        conflict = httpx.post(
            f"{base}/retry-safe/items", json={"operation_id": "same", "name": "two", "price": 1.0}
        )
        assert first.status_code == 201
        assert conflict.status_code == 409
        assert count_rows(db, "items") == count_rows(db, "operations") == 1


def test_concurrent_replay_recovers_from_bounded_write_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_server = server
    original_post = httpx.post
    starts = 0
    base_url = ""
    first_responses: list[tuple[int, object]] = []
    first_response_lock = threading.Lock()
    worker_state = threading.local()

    def release_gate() -> None:
        response = httpx.get(f"{base_url}/release-write-gate", timeout=3)
        assert response.status_code == 200, (response.status_code, response.text)

    first_attempts = threading.Barrier(8, action=release_gate, timeout=8)

    @contextlib.contextmanager
    def busy_first_server(
        tmp_path: Path, database: Path | None = None, *, hold_retry_lock: bool = False
    ) -> Iterator[tuple[str, Path, Path]]:
        nonlocal starts, base_url
        starts += 1
        with original_server(
            tmp_path, database, hold_retry_lock=hold_retry_lock or starts == 1
        ) as state:
            base_url = state[0]
            yield state

    def post(url: str, *, json: object) -> httpx.Response:
        response = original_post(url, json=json)
        if threading.current_thread() is not threading.main_thread() and not getattr(
            worker_state, "attempted", False
        ):
            worker_state.attempted = True
            observed = (response.status_code, response.json())
            with first_response_lock:
                first_responses.append(observed)
            assert observed == (503, {"detail": "retry write busy"}), observed
            first_attempts.wait()
        return response

    monkeypatch.setattr(sys.modules[__name__], "server", busy_first_server)
    monkeypatch.setattr(httpx, "post", post)
    test_operation_mapping_survives_restart_and_same_key_concurrent_posts(tmp_path)
    assert len(first_responses) == 8
    assert starts == 2


def post_replay(base: str, body: Mapping[str, object]) -> httpx.Response:
    response = httpx.post(f"{base}/retry-safe/items", json=body)
    # The application deliberately sheds contended writes after 250 ms. Keep
    # the operation ID unchanged, and retry only that documented busy response.
    for _ in range(2):
        if response.status_code != 503:
            break
        try:
            busy = response.json() == {"detail": "retry write busy"}
        except ValueError:
            busy = False
        if not busy:
            break
        response = httpx.post(f"{base}/retry-safe/items", json=body)
    return response


@pytest.mark.parametrize(
    ("status", "content", "expected_calls"),
    [
        (503, b'{"detail":"retry write busy"}', 3),
        (503, b'{"detail":"other failure"}', 1),
        (503, b"not JSON", 1),
        (500, b'{"detail":"internal server error"}', 1),
        (409, b'{"detail":"operation_id already used with a different payload"}', 1),
        (201, b'{"id":1,"name":"book","price":4.0}', 1),
    ],
)
def test_replay_attempts_are_bounded_and_only_retry_the_write_gate(
    monkeypatch: pytest.MonkeyPatch, status: int, content: bytes, expected_calls: int
) -> None:
    calls: list[object] = []
    body = {"operation_id": "same-operation", "name": "book", "price": 4.0}

    def post(url: str, *, json: object) -> httpx.Response:
        assert url == "http://example.test/retry-safe/items"
        calls.append(json)
        return httpx.Response(status, content=content)

    monkeypatch.setattr(httpx, "post", post)
    response = post_replay("http://example.test", body)
    assert response.status_code == status and response.content == content
    assert len(calls) == expected_calls
    assert all(sent is body for sent in calls)


def test_operation_mapping_survives_restart_and_same_key_concurrent_posts(tmp_path: Path) -> None:
    db = tmp_path / "restart.sqlite3"
    body = {"operation_id": "persisted", "name": "book", "price": 4.0}
    with server(tmp_path, db) as (base, _db, _events):
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(lambda _: post_replay(base, body), range(8)))
        assert all(r.status_code == 201 for r in responses), [
            (r.status_code, r.text) for r in responses
        ]
        assert len({r.json()["id"] for r in responses}) == 1
        expected = responses[0].json()
    with server(tmp_path, db) as (base, _db, _events):
        replay = httpx.post(f"{base}/retry-safe/items", json=body)
        assert replay.status_code == 201 and replay.json() == expected
        assert count_rows(db, "items") == count_rows(db, "operations") == 1


@pytest.mark.parametrize(
    "body",
    [
        {"operation_id": "", "name": "x", "price": 1.0},
        {"operation_id": "x" * 257, "name": "x", "price": 1.0},
        {"operation_id": "x", "name": "x", "price": float("nan")},
        {"operation_id": "x", "name": "x", "price": float("inf")},
    ],
)
def test_invalid_operation_or_price_rejected_before_lease(
    tmp_path: Path, body: dict[str, object]
) -> None:
    with server(tmp_path) as (base, db, events):
        response = httpx.post(
            f"{base}/retry-safe/items",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert not events.exists() or '"event": "acquire"' not in events.read_text()
        assert count_rows(db, "items") == count_rows(db, "operations") == 0


def test_database_constraint_failure_rolls_back_item_and_mapping(tmp_path: Path) -> None:
    with server(tmp_path) as (base, db, _events):
        with contextlib.closing(sqlite3.connect(db)) as conn:
            conn.execute(
                "CREATE TRIGGER reject_operation BEFORE INSERT ON operations BEGIN SELECT RAISE(ABORT, 'no'); END"
            )
            conn.commit()
        response = httpx.post(
            f"{base}/retry-safe/items", json={"operation_id": "atomic", "name": "x", "price": 1.0}
        )
        assert response.status_code == 500
        assert count_rows(db, "items") == count_rows(db, "operations") == 0


def test_retry_demo_client_runs_bounded_two_attempt_flow(tmp_path: Path) -> None:
    with server(tmp_path) as (base, db, _events):
        proc = subprocess.run(
            [sys.executable, str(EXAMPLE), "--retry-demo"],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT / "src"),
                "DEXPOT_EXAMPLE_HOST": "127.0.0.1",
                "DEXPOT_EXAMPLE_PORT": base.rsplit(":", 1)[1],
            },
            capture_output=True,
            text=True,
            timeout=12,
        )
        # Re-run against this server's exact port supplied by its URL.
        if proc.returncode != 0:
            pytest.fail(
                f"client failed: {proc.stderr}; DEXPOT_EXAMPLE_PORT must target test server"
            )
        result = json.loads(proc.stdout)
        assert result["first_status"] == 500 and result["retry_status"] == 201
        assert result["item"]["id"] > 0
        assert count_rows(db, "items") == count_rows(db, "operations") == 1
