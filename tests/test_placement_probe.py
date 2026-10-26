"""Protocol tests; synthetic records below are not benchmark evidence."""

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/placement_probe.py"


def test_complete_calibration_schedule_preserves_cells_and_reverses_order():
    api = runpy.run_path(str(SCRIPT))
    matrix = [
        {"id": f"cell-{i}", "runtime": "ft", "profile": "flat", "repeat": i} for i in range(12)
    ]
    rows = api["calibration_schedule"](matrix)
    assert len(rows) == 24 and len({r["id"] for r in rows}) == 24
    for i, cell in enumerate(matrix):
        pair = rows[i * 2 : i * 2 + 2]
        assert all(r["cell"] == cell and r["placement"] == "disjoint" for r in pair)
        assert [r["side"] for r in pair] == (["left", "right"] if i % 2 == 0 else ["right", "left"])
    good = [{"comparison": {"status": "screen-passed"}} for _ in range(12)]
    verdict = api["calibration_verdict"]([{"valid": True}] * 24, good)
    assert verdict == {"status": "calibration-only-passed", "candidate_qualified": False}
    good[0]["comparison"]["status"] = "regression"
    assert api["calibration_verdict"]([{"valid": True}] * 24, good)["status"] == "invalid-control"


def test_equal_cpu_budgets_change_overlap_only():
    select = runpy.run_path(str(SCRIPT))["placements"]
    selected = select([2, 4, 6, 8])
    assert selected == {
        "overlap": {"server": [2, 4], "client": [2, 4]},
        "disjoint": {"server": [2, 4], "client": [6, 8]},
    }
    with pytest.raises(ValueError, match="four"):
        select([2, 4])


def test_frozen_schedule_and_verdict_never_qualify_feature():
    api = runpy.run_path(str(SCRIPT))
    schedule = api["schedule"]()
    assert len(schedule) == 8
    assert len({row["id"] for row in schedule}) == 8
    for mode in ("gil", "ft"):
        assert [r["placement"] for r in schedule if r["runtime"] == mode] == [
            "overlap",
            "disjoint",
            "disjoint",
            "overlap",
        ]
    assert api["diagnostic_verdict"]([{"valid": True}] * 8) == {
        "status": "diagnostic-complete",
        "candidate_qualified": False,
    }
    assert api["diagnostic_verdict"]([{"valid": True}] * 7)["status"] == "diagnostic-incomplete"
    assert api["diagnostic_verdict"]([{"valid": False}] * 8)["status"] == "diagnostic-invalid"
