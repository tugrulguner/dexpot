"""The published diagnostic summary is data, not a new performance claim."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/regression"


def test_recorded_baseline_is_complete_and_matches_the_frozen_harness():
    summary = json.loads((ROOT / "baseline-macos-v071.json").read_text())
    plan = json.loads((ROOT / "plan.json").read_text())
    assert summary["kind"] == "diagnostic-baseline-not-candidate-acceptance"
    assert summary["plan"] == plan
    assert summary["expected"] == summary["completed"] == summary["valid"] == len(plan["matrix"])
    assert set(summary["raw_trial_sha256"]) == {cell["id"] for cell in plan["matrix"]}
    assert summary["validated_replies"] > 0
    assert summary["bad_replies"] == summary["transport_errors"] == 0
    for key, name in {
        "application": "application.py",
        "validator": "validate.lua",
        "runner": "run.py",
        "evaluator": "evaluate.py",
        "plan": "plan.json",
    }.items():
        assert (
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == summary["fingerprints"][key]
        )
    assert summary["artifact"]["digests"]["sha256"] == summary["fingerprints"]["wheel"]
    assert len(summary["groups"]) == 6
    assert sum(group["trials"] for group in summary["groups"]) == summary["completed"]
    old = summary["retained_invalid_generation"]
    assert old["status"] == "invalid" and old["completed"] == 12 and old["valid"] == 10
    assert len(old["failed_cells"]) == 2
