"""Routing probe correctness fixtures, not benchmark observations."""

import runpy
from pathlib import Path

import pytest

from dexpot import Dex

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/route_lookup_probe.py"


def test_explicit_original_fallback_is_not_rebound_to_probe_wrapper(monkeypatch):
    app = Dex()
    app._compile()
    original = app._match
    api = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(
        app, "_match", lambda *_: (_ for _ in ()).throw(AssertionError("recursive wrapper"))
    )
    lookup, _ = api["bind_lookup"](app, "local-proxy", fallback=original)
    assert lookup("GET", "/missing") == original("GET", "/missing")


@pytest.mark.parametrize("strategy", ["bound-shared", "local-proxy", "local-dict"])
def test_bound_probe_preserves_route_identity_captures_and_method_resolution(strategy):
    app = Dex()

    @app.get("/flat")
    def flat():
        return {"ok": True}

    @app.get("/items/{item_id}")
    def item(item_id: int):
        return {"id": item_id}

    app._compile()
    bind = runpy.run_path(str(SCRIPT))["bind_lookup"]
    lookup, evidence = bind(app, strategy)
    for method, path in [
        ("GET", "/flat"),
        ("POST", "/flat"),
        ("GET", "/items/7"),
        ("GET", "/missing"),
    ]:
        expected, actual = app._match(method, path), lookup(method, path)
        assert actual[0] is expected[0]
        assert actual[1:] == expected[1:]
    assert evidence["same_route_values"] is True
    assert evidence["owns_mapping"] is (strategy != "bound-shared")
