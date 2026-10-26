"""Read-only host metadata must not require macOS tools on Linux."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_linux_metadata_does_not_invoke_pmset(monkeypatch, tmp_path):
    api = runpy.run_path(str(ROOT / "scripts/controlled_lifecycle_qualification.py"))
    monkeypatch.setattr(api["sys"], "platform", "linux")

    def forbidden(*args, **kwargs):
        raise AssertionError("Linux metadata must not invoke pmset")

    monkeypatch.setattr(api["subprocess"], "check_output", forbidden)
    observed = api["power_snapshot"](tmp_path / "absent-governor")
    assert observed == {"platform": "linux", "cpu0_governor": None}
