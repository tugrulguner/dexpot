"""Protocol tests; synthetic records below are not benchmark evidence."""

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/placement_probe.py"


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
