"""CPU placement is a calibration experiment, never candidate acceptance."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_calibration_only_never_launches_candidate_measurements():
    api = runpy.run_path(str(ROOT / "scripts/controlled_lifecycle_qualification.py"))
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append(cohort)
        return {"id": cell["id"], "comparison": {"status": "screen-passed"}}

    aa, ab, enabled = api["collect_cohorts"](
        [{"id": "one"}], pair, "ordinary", "enabled", calibration_only=True
    )
    assert calls == ["aa"] and ab == [] and enabled is None
    assert (
        api["decide"](aa, ab, enabled, ["one"], calibration_only=True) == "calibration-only-passed"
    )


def test_affinity_experiment_scopes_placement_and_restores_state(monkeypatch):
    api = runpy.run_path(str(ROOT / "scripts/controlled_lifecycle_qualification.py"))
    scope = api["main"].__globals__
    monkeypatch.setattr(api["sys"], "platform", "linux")
    calls = []
    monkeypatch.setattr(api["os"], "sched_getaffinity", lambda pid: {2, 5}, raising=False)
    monkeypatch.setattr(
        api["os"], "sched_setaffinity", lambda pid, cpus: calls.append((pid, cpus)), raising=False
    )
    monkeypatch.setenv("DEXPOT_BENCH_CALIBRATION_ONLY", "prior")
    monkeypatch.setenv("DEXPOT_BENCH_ORIGINAL_AFFINITY", "prior")

    def main():
        assert api["os"].environ["DEXPOT_BENCH_CALIBRATION_ONLY"] == "1"
        assert json.loads(api["os"].environ["DEXPOT_BENCH_ORIGINAL_AFFINITY"]) == [2, 5]
        return 7

    monkeypatch.setitem(scope, "main", main)
    assert api["affinity_controls"]() == 7
    assert calls == [(0, {2}), (0, {2, 5})]
    assert api["os"].environ["DEXPOT_BENCH_CALIBRATION_ONLY"] == "prior"
    assert api["os"].environ["DEXPOT_BENCH_ORIGINAL_AFFINITY"] == "prior"
