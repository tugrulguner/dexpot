import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "route_lookup_http_probe.py"
spec = importlib.util.spec_from_file_location("route_lookup_http_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_owned_bindings_are_thread_local_and_hooks_restore(tmp_path, monkeypatch):
    import runpy
    import threading
    from types import MappingProxyType, SimpleNamespace

    root = SCRIPT.parent
    monkeypatch.syspath_prepend(str(root))
    install = runpy.run_path(str(root / "route_lookup_http_fixture.py"))["install"]
    barrier = threading.Barrier(2, timeout=3)
    value = object()
    failures = []

    class App:
        def __init__(self):
            self._plan = SimpleNamespace(
                router=SimpleNamespace(literal=MappingProxyType({("GET", "/flat"): value}))
            )
            self.original_calls = 0

        def _match(self, method, path):
            self.original_calls += 1
            return value, [], ()

        def _own_connection(self, conn, buf, *, registered=False):
            barrier.wait()
            assert self._match("GET", "/flat")[0] is value

        def serve(self):
            def work():
                try:
                    self._own_connection(None, b"")
                except BaseException as exc:
                    failures.append(exc)

            workers = [threading.Thread(target=work) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=4)
            assert not any(worker.is_alive() for worker in workers)

    monkeypatch.setenv("ROUTE_LOOKUP_STRATEGY", "local-proxy")
    monkeypatch.setenv("ROUTE_LOOKUP_REPORT", str(tmp_path / "old-report.json"))
    monkeypatch.chdir(tmp_path)
    original = App._match
    app = App()
    install(app, ft=True)
    app.serve()
    assert not failures
    assert app.original_calls == 0
    assert App._match is original


def test_trial_schedule_is_balanced_and_bounded():
    assert probe.SCHEDULE == [
        "original",
        "bound-shared",
        "local-proxy",
        "local-proxy",
        "bound-shared",
        "original",
    ]
    assert probe.TRIAL_SECONDS == 30


def test_strategy_env_is_explicit_and_restorable(monkeypatch):
    monkeypatch.setenv("ROUTE_LOOKUP_STRATEGY", "prior")
    with probe.strategy_environment("local-proxy"):
        assert __import__("os").environ["ROUTE_LOOKUP_STRATEGY"] == "local-proxy"
    assert __import__("os").environ["ROUTE_LOOKUP_STRATEGY"] == "prior"


def test_result_never_claims_candidate_qualification():
    result = probe.result_document([])
    assert result["candidate_qualified"] is False
    assert result["kind"] == "same-artifact-routing-ownership-ablation"
