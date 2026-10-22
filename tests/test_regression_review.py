"""Synthetic unit records exercise comparison rejection, never performance evidence."""

import argparse
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def recording_pair(tmp_path):
    records = runpy.run_path(str(ROOT / "tests/test_regression_evaluate.py"))["records"]
    folders = []
    for side, digit in (("baseline", "a"), ("candidate", "b")):
        folder = tmp_path / side
        folder.mkdir()
        plan, rows, controls = records()
        fingerprints = {"runner": "c" * 64, "wheel": digit * 64}
        identities = {}
        for row in rows:
            mode = row["cell"]["runtime"]
            row["runtime"].update(parser="python", selected_ft=mode == "ft")
            row["runtime"]["version"] = "0.7.1" if side == "baseline" else "0.8.0"
            row["fingerprints"] = fingerprints
            identities[mode] = dict(
                row["runtime"],
                source_sha256=digit * 64,
                python="unit-test-interpreter",
                msgspec="unit-test-codec",
            )
            controls[mode].update(
                runtime=row["runtime"],
                fingerprints=fingerprints,
                limits={"DEXPOT_POOL": "2", "DEXPOT_MAX_QUEUE": "2", "DEXPOT_MAX_CONNECTIONS": "4"},
            )
            (folder / (row["cell"]["id"] + ".json")).write_text(json.dumps(row))
            (folder / (mode + ".preflight.json")).write_text(json.dumps(controls[mode]))
        manifest = dict(
            plan=plan,
            platform="synthetic-test",
            machine="synthetic-test",
            cpu_count=1,
            psutil="unit-test-monitor",
            controller_python="unit-test-controller",
            fingerprints=fingerprints,
            runtime=identities,
        )
        (folder / "manifest.json").write_text(json.dumps(manifest))
        folders.append(folder)
    return argparse.Namespace(
        baseline=folders[0], candidate=folders[1], output=tmp_path / "comparison.json"
    )


def test_comparison_permits_distinct_versions_bound_to_their_own_manifest(tmp_path):
    args = recording_pair(tmp_path)
    compare = runpy.run_path(str(ROOT / "benchmarks/regression/run.py"))["compare_directories"]
    assert compare(args) == 0
    assert len(json.loads(args.output.read_text())["pairs"]) == 2


@pytest.mark.parametrize(
    "location,key,value",
    [
        ("gil-flat-0.json", "version", "wrong-version"),
        ("gil-flat-0.json", "module", "/other/site-packages/dexpot/__init__.py"),
        ("gil-flat-0.json", "parser", "native"),
        ("gil-flat-0.json", "selected_ft", True),
        ("gil.preflight.json", "version", "wrong-version"),
    ],
)
def test_comparison_rejects_observations_detached_from_manifest(tmp_path, location, key, value):
    args = recording_pair(tmp_path)
    path = args.candidate / location
    data = json.loads(path.read_text())
    data["runtime"][key] = value
    path.write_text(json.dumps(data))
    compare = runpy.run_path(str(ROOT / "benchmarks/regression/run.py"))["compare_directories"]
    assert compare(args) == 1
    assert json.loads(args.output.read_text())["status"] == "invalid"


@pytest.mark.parametrize(
    "location,key",
    [
        ("gil-flat-0.json", "fingerprints"),
        ("gil.preflight.json", "fingerprints"),
        ("gil.preflight.json", "limits"),
    ],
)
def test_comparison_requires_control_and_trial_provenance(tmp_path, location, key):
    args = recording_pair(tmp_path)
    path = args.candidate / location
    data = json.loads(path.read_text())
    data[key] = {}
    path.write_text(json.dumps(data))
    compare = runpy.run_path(str(ROOT / "benchmarks/regression/run.py"))["compare_directories"]
    assert compare(args) == 1
