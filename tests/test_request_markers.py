"""Unit fixtures are synthetic; real native HTTP smoke is separate evidence."""

import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location(
        "request_marker_sidecar", ROOT / "scripts/request_marker_sidecar.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_binding_headers_and_thread_isolation(tmp_path, monkeypatch):
    sidecar = load()
    barrier = threading.Barrier(2)

    def read(marker):
        barrier.wait(timeout=3)
        return SimpleNamespace(headers={"x-dexpot-diag-id": marker}), b""

    module = SimpleNamespace(read_request=read)
    monkeypatch.setattr(sidecar.importlib, "import_module", lambda name: module)

    class App:
        @staticmethod
        def _send(conn, status, out, **kwargs):
            conn.append((status, out, kwargs))

    monkeypatch.setenv("DIAG_DIR", str(tmp_path))
    sidecar.install(App())
    installed_read = module.read_request
    assert isinstance(vars(App)["_send"], staticmethod)
    results = {}

    def worker(marker):
        conn = []
        module.read_request(marker)
        App._send(conn, 200, b"{}", keep_alive=True)
        results[marker] = conn

    workers = [threading.Thread(target=worker, args=(f"100-{i}-64",)) for i in [1, 2]]
    for t in workers:
        t.start()
    for t in workers:
        t.join(timeout=4)
    assert not any(t.is_alive() for t in workers)
    assert module.read_request is installed_read
    for marker, conn in results.items():
        assert conn[0][1] == b"{}" and conn[0][2]["extra_headers"] == ((sidecar.HEADER, marker),)
    assert len(results) == 2
    sidecar.flush()
    rows = [
        json.loads(line)
        for p in tmp_path.glob("server-*.jsonl")
        for line in p.read_text().splitlines()
    ]
    assert len([r for r in rows if r.get("event") == "Sparsed"]) == 2


def test_lua_preserves_original_callbacks_and_request_bytes():
    lua = (ROOT / "scripts/request_marker_client.lua").read_text()
    assert "old_response(status, headers, body)" in lua
    assert "old_done(summary, latency, requests)" in lua
    assert "base = wrk.format()" in lua and "base:gsub" in lua
    assert "diag_pending" in lua and "diag_dropped" in lua


def test_thread_local_sample_does_not_leak():
    sidecar = load()
    sidecar._tls.sample = "main"
    seen = []
    t = threading.Thread(target=lambda: seen.append(getattr(sidecar._tls, "sample", None)))
    t.start()
    t.join(timeout=3)
    assert seen == [None]
