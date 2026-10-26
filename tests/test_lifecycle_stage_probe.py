"""Unit fixtures for phase attribution; not timing evidence."""

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/lifecycle_stage_probe.py"


def test_exclusive_residual_does_not_double_count_stage_spans():
    api = runpy.run_path(str(SCRIPT))
    row = api["snapshot"](
        "/io", (100, 40), {"read": (20, 5), "handler": (30, 10), "encode": (10, 5)}
    )
    assert row["residual"] == [40, 20]
    assert row["total"] == [100, 40]
    assert row["path"] == "/io"


def test_fixture_preserves_handler_bodies_and_adds_only_diagnostics():
    import ast

    api = runpy.run_path(str(SCRIPT))
    source = (SCRIPT.parent / "lifecycle_preflight_harness/application.py").read_text()
    changed = api["instrument_application"](source)
    before, after = ast.parse(source), ast.parse(changed)
    handlers = ("flat", "nested", "cpu", "io")
    for name in handlers:
        old = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == name)
        new = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert [ast.dump(n) for n in old.body] == [ast.dump(n) for n in new.body]
        assert len(new.decorator_list) == len(old.decorator_list) + 1
    assert "finally:\n        stage_report()" in changed


def test_stage_probe_is_only_two_mixed_pairs_and_never_enabled():
    api = runpy.run_path(str(SCRIPT.parent / "controlled_lifecycle_qualification.py"))
    calls = []
    matrix = [{"id": "ft-mixed-1", "runtime": "ft", "profile": "mixed", "repeat": 1}]

    def pair(cell, cohort, sides, reverse):
        calls.append((cell, cohort, reverse))
        return {"comparison": {"status": "regression"}}

    aa, ab, enabled = api["collect_cohorts"](
        matrix, pair, "ordinary", "enabled", stage_diagnostic=True
    )
    assert aa == [] and len(ab) == 2 and enabled is None
    assert [item[2] for item in calls] == [False, True]
    assert all(item[0] == matrix[0] for item in calls)


def test_diagnostic_sidecars_do_not_enter_flat_trial_inventory(tmp_path):
    api = runpy.run_path(str(SCRIPT))
    target = api["report_path"](tmp_path, 123)
    target.parent.mkdir(exist_ok=True)
    target.write_text("{}")
    assert target.name == "stage-report-123.json"
    assert target.parent == tmp_path / "stage-probes"
    assert list(tmp_path.glob("*.json")) == []


def test_negative_residual_is_clamped_and_labeled():
    api = runpy.run_path(str(SCRIPT))
    row = api["snapshot"]("/flat", (10, 5), {"send": (11, 6)})
    assert row["residual"] == [0, 0]
    assert row["overlap_or_clock_error"] is True
