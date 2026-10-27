"""Synthetic clock fixtures exercise joins; never presented as measured evidence."""

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "marker_analysis", Path(__file__).parents[1] / "scripts/analyze_request_markers.py"
)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_overlapping_send_return_and_partial_unknown(tmp_path):
    logs = tmp_path / "markers"
    logs.mkdir()
    events = []
    for name, wall, mono, cpu in [
        ("Crequest_prepared", 0, 0, 0),
        ("Sparsed", 100, 100000, 0),
        ("Ssend_entry", 200, 200000, 1000),
        ("Ssend_return", 20000, 20000000, 2000),
        ("Cresponse_callback_entry", 15000, 0, 0),
    ]:
        events.append(
            {"id": "1-1-64", "event": name, "wall_us": wall, "mono_ns": mono, "thread_cpu_ns": cpu}
        )
    events.append({"id": "1-1-128", "event": "Sparsed", "wall_us": 30000})
    (logs / "unit.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    footer = {
        "prepared": 2,
        "received": 1,
        "pending": 1,
        "dropped": 0,
        "clock_errors": 0,
        "unmatched": 0,
    }
    windows = [
        {
            "index": i,
            "pid": 1,
            "checks_pass": True,
            "raw": {
                "metrics": {"unit_only": True},
                "stdout": "DIAG_SUMMARY " + json.dumps(footer) if i == 1 else "",
            },
        }
        for i in range(3)
    ]
    (tmp_path / "windows.json").write_text(json.dumps(windows))
    result = MOD.analyze(tmp_path)
    assert result["complete_valid_matched_ids"] == 1
    assert result["send_return_after_client_count"] == 1
    assert result["invalid_or_partial_ids"]["missing_or_duplicate_boundary"] == 1
    assert result["slow_dominant_80pct_counts"] == {"post_send_entry_us": 1}
    assert result["qualified"] is False
