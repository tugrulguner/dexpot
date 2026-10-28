import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "wake_focus", Path(__file__).resolve().parents[1] / "scripts/socket_wake_ablation.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_retries_are_rejected_before_any_work(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setattr(sys, "argv", ["focus", "--run"])
    with pytest.raises(ValueError, match="no retries"):
        module.main()


def test_wrong_prepared_artifact_is_rejected(tmp_path, monkeypatch):
    evidence = tmp_path / "dexpot-socket-runtime-qualification/evidence"
    evidence.mkdir(parents=True)
    (evidence / "preparation-only.json").write_text(
        json.dumps({"head_sha": "wrong", "qualified": False})
    )
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(AssertionError):
        module.measure()
    assert not (evidence / "wake-focus").exists()


def test_cli_dispatches_to_real_measurement_api(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(sys, "argv", ["focus", "--run"])
    calls = []
    monkeypatch.setattr(module, "measure", lambda: calls.append("measure"))
    module.main()
    assert calls == ["measure"]
