"""Unit checks for predeclared campaign stages, not measurement evidence."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_failed_calibration_does_not_launch_candidate_or_enabled_trials():
    api = runpy.run_path(str(ROOT / "scripts/controlled_lifecycle_qualification.py"))
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append((cell["id"], cohort))
        status = "regression" if cell["id"] == "one" else "screen-passed"
        return {"id": cell["id"], "comparison": {"status": status}}

    aa, ab, enabled = api["collect_cohorts"](
        [{"id": "one"}, {"id": "two"}], pair, "ordinary", "enabled"
    )
    assert calls == [("one", "aa"), ("two", "aa")]
    assert len(aa) == 2 and ab == [] and enabled is None


def test_each_complete_stage_passes_before_the_next_starts():
    api = runpy.run_path(str(ROOT / "scripts/controlled_lifecycle_qualification.py"))
    calls = []

    def pair(cell, cohort, sides, reverse):
        calls.append((cell["id"], cohort, reverse))
        return {"id": cell["id"], "comparison": {"status": "screen-passed"}}

    aa, ab, enabled = api["collect_cohorts"](
        [{"id": "one"}, {"id": "two"}], pair, "ordinary", "enabled"
    )
    assert [cohort for _, cohort, _ in calls] == ["aa", "aa", "ab", "ab", "enabled", "enabled"]
    assert [reverse for _, _, reverse in calls] == [False, True] * 3
    assert len(aa) == len(ab) == len(enabled) == 2
