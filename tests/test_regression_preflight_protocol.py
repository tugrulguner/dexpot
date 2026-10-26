"""Deterministic regressions for the benchmark's preflight protocol."""

import contextlib
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_reports_successful_cleanup_after_an_overload_error(monkeypatch, tmp_path):
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/run.py"))
    preflight = api["preflight"]
    scope = preflight.__globals__
    state = {"runtime": {}, "cleanup_pass": False}

    @contextlib.contextmanager
    def server(*args):
        try:
            yield None, 12345, state
        finally:
            state["cleanup_pass"] = True

    calls = 0

    def request(port, path):
        nonlocal calls
        calls += 1
        if calls <= 8:
            return 200, scope["FLAT"]
        raise TimeoutError("retained overload failure")

    class Connection:
        def close(self):
            pass

    monkeypatch.setitem(scope, "server", server)
    monkeypatch.setitem(scope, "verify_runtime", lambda *args: None)
    monkeypatch.setitem(scope, "request", request)
    monkeypatch.setitem(scope, "_wait_preflight_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(scope["socket"], "create_connection", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(scope["time"], "sleep", lambda _: None)
    result = preflight("python", {}, tmp_path / "preflight.log", {}, "gil", {})
    assert not result["overload_pass"]
    assert result["error"] == "TimeoutError('retained overload failure')"
    assert result["cleanup_pass"], "cleanup succeeded even though the overload check failed"


@pytest.mark.parametrize(
    ("mode", "worker_start_delayed"), [("gil", False), ("gil", True), ("ft", False)]
)
def test_preflight_waits_for_churn_quiescence_before_filling_capacity(
    monkeypatch, tmp_path, mode, worker_start_delayed
):
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/run.py"))
    preflight = api["preflight"]
    scope = preflight.__globals__
    state = {"runtime": {}, "cleanup_pass": False}
    world = {"prior": True, "barrier": False, "snapshots": 0, "claimed": False}
    peers = []

    def occupancy():
        return int(world["prior"]) + int(world["barrier"]) + sum(peer.accepted for peer in peers)

    @contextlib.contextmanager
    def server(*args):
        try:
            yield None, 12345, state
        finally:
            state["cleanup_pass"] = True

    class Peer:
        def __init__(self):
            queued = sum(peer.accepted for peer in peers) - int(world["claimed"])
            self.accepted = queued < 2 if worker_start_delayed else occupancy() < 4
            self.rejected = not self.accepted
            peers.append(self)

        def close(self):
            self.accepted = False

    class Response:
        status = 200

        def read(self):
            total = occupancy()
            active = (
                int(world["prior"]) + int(world["barrier"]) + int(world["claimed"])
                if worker_start_delayed
                else min(2, total)
            )
            return json.dumps(
                {
                    "active": total if mode == "ft" else active,
                    "queued": 0 if mode == "ft" else total - active,
                    "available_ft": 4 - total if mode == "ft" else None,
                    "live_ft_owners": total if mode == "ft" else None,
                }
            ).encode()

    class Barrier:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path):
            assert method == "GET" and path == "/_preflight"
            world["barrier"] = True
            world["snapshots"] += 1
            if world["snapshots"] >= 2:
                world["prior"] = False
            if worker_start_delayed and any(peer.accepted for peer in peers):
                world["claimed"] = True

        def getresponse(self):
            return Response()

        def close(self):
            world["barrier"] = False

    calls = 0

    def request(port, path):
        nonlocal calls
        calls += 1
        if calls <= 8:
            return 200, scope["FLAT"]
        # A prior churn owner finally releases here. Filling capacity before
        # quiescence has already rejected a held peer, leaving this request
        # admitted behind incomplete requests rather than receiving a 503.
        world["prior"] = False
        if occupancy() == 4:
            return 503, b""
        raise TimeoutError("overload request admitted behind incomplete peers")

    monkeypatch.setitem(scope, "server", server)
    monkeypatch.setitem(scope, "verify_runtime", lambda *args: None)
    monkeypatch.setitem(scope, "request", request)
    monkeypatch.setattr(scope["http"].client, "HTTPConnection", Barrier)
    monkeypatch.setattr(scope["socket"], "create_connection", lambda *args, **kwargs: Peer())
    monkeypatch.setattr(scope["time"], "sleep", lambda _: None)
    if worker_start_delayed:
        clock = iter(range(10000))
        monkeypatch.setattr(scope["time"], "monotonic", lambda: next(clock))
    result = preflight("python", {}, tmp_path / "preflight.log", {}, mode, {})
    assert result["overload_pass"], result
    assert "error" not in result
    assert not any(peer.rejected for peer in peers)
    assert world["snapshots"] >= 3
    assert result["cleanup_pass"]


def test_ft_quiescence_allows_dead_owners_waiting_for_admission_reaping(monkeypatch):
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/run.py"))
    observed = {"active": 1, "queued": 0, "live_ft_owners": 1, "available_ft": 2}

    class Response:
        status = 200

        def read(self):
            return json.dumps(observed).encode()

    class Connection:
        def request(self, *args):
            pass

        def getresponse(self):
            return Response()

    clock = iter([0.0, 3.0])
    monkeypatch.setattr(api["time"], "monotonic", lambda: next(clock))
    assert api["_wait_preflight_state"](Connection(), "ft", full=False) == observed


@pytest.mark.parametrize("enabled", [False, True])
def test_admission_observer_is_absent_from_timed_application(monkeypatch, enabled):
    if enabled:
        monkeypatch.setenv("DEXPOT_PREFLIGHT_BARRIER", "1")
    else:
        monkeypatch.delenv("DEXPOT_PREFLIGHT_BARRIER", raising=False)
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/application.py"))
    app = api["app"]
    endpoint, _, _ = app._match("GET", "/_preflight")
    assert (endpoint is not None) is enabled
    assert len(app._plan.endpoints) == (6 if enabled else 5)
