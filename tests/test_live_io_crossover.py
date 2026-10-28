import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

from dexpot import Dex


def controls(monkeypatch):
    original = Dex.serve
    path = (
        Path(__file__).resolve().parents[1] / "scripts/live_io_crossover/collector/sitecustomize.py"
    )
    spec = importlib.util.spec_from_file_location("live_io_hook", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        Dex.serve = original
    monkeypatch.setattr(module, "original", lambda *a, **kw: None)
    conn = object()
    held = SimpleNamespace(_lock=threading.Lock(), _states={conn: object()}, close=lambda: None)
    routes = {}

    class App:
        def __init__(self):
            self._cond = threading.Condition()
            self._active_connections = {conn}
            self._work = []
            self._gil_io = held

        def get(self, path):
            return lambda handler: routes.setdefault(path, handler)

    app = App()
    module.serving(app)
    return app, routes, held


def test_overlapping_connection_prevents_mode_change(monkeypatch):
    app, routes, held = controls(monkeypatch)
    app._active_connections.add(object())
    payload, status = routes["/_wake_diag/off"]()
    assert status == 409 and payload["detail"] == "not quiescent"
    assert app._gil_io is held


def test_queued_work_prevents_mode_change(monkeypatch):
    app, routes, held = controls(monkeypatch)
    app._work.append(object())
    assert routes["/_wake_diag/off"]()[1] == 409
    assert app._gil_io is held


def test_quiescent_switch_changes_only_future_connection_selection(monkeypatch):
    app, routes, held = controls(monkeypatch)
    before = routes["/_wake_diag/status"]()
    assert before["mode"] is True and before["connection_owned"] is True
    after = routes["/_wake_diag/off"]()
    assert after["mode"] is False
    assert after["connection_owned"] is True  # Current control still has its old channel.
    assert app._gil_io is None
    conn = object()
    app._active_connections = {conn}
    assert routes["/_wake_diag/status"]()["connection_owned"] is False
    assert routes["/_wake_diag/on"]()["mode"] is True
    assert app._gil_io is held
