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


def test_qualification_wrappers_keep_equal_disjoint_budgets(tmp_path, monkeypatch):
    api = runpy.run_path(str(SCRIPT))
    prepare = api["prepare_disjoint"]
    calls = []
    monkeypatch.setitem(
        prepare.__globals__,
        "launcher",
        lambda path, binary, cpus: calls.append((path, binary, cpus)),
    )
    binary = tmp_path / "wrk"
    binary.write_bytes(b"test-fixture-not-native-client")
    pythons = {("main", "gil"): tmp_path / "python-gil", ("pr", "ft"): tmp_path / "python-ft"}
    wrapped, client, metadata = prepare(pythons, binary, tmp_path, [0, 1, 2, 3])
    assert set(wrapped) == set(pythons)
    assert client != binary
    assert [c[2] for c in calls] == [[0, 1], [0, 1], [2, 3]]
    assert metadata["server_cpus"] == [0, 1] and metadata["client_cpus"] == [2, 3]
    assert metadata["candidate_qualified"] is False


def test_affinity_attestation_rejects_wrong_masks_or_unattested_serving_pid(tmp_path):
    import json

    api = runpy.run_path(str(SCRIPT))
    validate = api["validate_placement"]
    launchers = tmp_path / "placement-launchers"
    launchers.mkdir()
    server = launchers / "main-ft.launches.jsonl"
    client = launchers / "native-client.launches.jsonl"
    server.write_text(json.dumps({"pid": 11, "affinity": [0, 1]}) + "\n")
    client.write_text(json.dumps({"pid": 12, "affinity": [2, 3]}) + "\n")
    metadata = {"server_cpus": [0, 1], "client_cpus": [2, 3]}
    assert validate(tmp_path, metadata, {11})["passed"] is True
    assert validate(tmp_path, metadata, {99})["passed"] is False
    client.write_text(json.dumps({"pid": 12, "affinity": [0, 1]}) + "\n")
    assert validate(tmp_path, metadata, {11})["passed"] is False


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
