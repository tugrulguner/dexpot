"""Real retained A/A gain must not count as repeatable calibration."""

import ast
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "scripts/lifecycle_preflight_harness"
FIXTURE = Path(__file__).parent / "fixtures/calibration-asymmetric-gain"


def calibration():
    tree = ast.parse((ROOT / "scripts/controlled_lifecycle_qualification.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    node = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "calibrate")
    namespace = {"runpy": runpy, "json": json, "harness": H}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "<actual-calibration>", "exec"), namespace
    )
    return namespace["calibrate"]


def test_large_same_source_gain_is_not_repeatable_control():
    result = calibration()(FIXTURE / "left", FIXTURE / "right", {"id": "gil-flat-1"})
    assert result["status"] == "regression", result
    assert result["pairs"][0]["forward_passed"] is True
    assert result["pairs"][0]["reverse_passed"] is False
    assert result["pairs"][0]["passed"] is False
    assert result["reverse_comparison"]["status"] == "regression"


def test_identical_recording_remains_repeatable():
    result = calibration()(FIXTURE / "left", FIXTURE / "left", {"id": "gil-flat-1"})
    assert result["status"] == "screen-passed", result
    assert result["pairs"][0]["forward_passed"] and result["pairs"][0]["reverse_passed"]


def test_swapping_control_sides_does_not_hide_nonrepeatability():
    result = calibration()(FIXTURE / "right", FIXTURE / "left", {"id": "gil-flat-1"})
    assert result["status"] == "regression"
    assert result["pairs"][0]["forward_passed"] is False
    assert result["pairs"][0]["reverse_passed"] is True


def test_product_comparison_still_accepts_a_speedup():
    compare = runpy.run_path(str(H / "evaluate.py"))["compare"]
    manifest = json.loads((FIXTURE / "left/manifest.json").read_text())
    left = json.loads((FIXTURE / "left/gil-flat-1.json").read_text())
    right = json.loads((FIXTURE / "right/gil-flat-1.json").read_text())
    result = compare(manifest["plan"], [left], [right])
    assert result["status"] == "screen-passed"
    assert result["pairs"][0]["goodput_ratio"] > 2
