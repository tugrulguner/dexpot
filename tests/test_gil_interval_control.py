"""Actual process-local interval activation; no parent interpreter policy changes."""

import json
import os
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).parents[1] / "scripts/gil_interval_control.py"


def test_actual_owned_child_activation_and_restore(tmp_path):
    control = tmp_path / "control.json"
    attest = tmp_path / "attest"
    attest.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHON_GIL", "PYTHONPATH")}
    env.update(DIAG_INTERVAL_CONTROL=str(control), DIAG_INTERVAL_ATTEST=str(attest))
    program = """import json,os,runpy,sys
from pathlib import Path
api=runpy.run_path(sys.argv[1]);control=Path(os.environ['DIAG_INTERVAL_CONTROL'])
stock=sys.getswitchinterval()
try:
 for index,value in enumerate([0.005,0.0005,0.0005,0.005]):
  control.write_text(json.dumps({'sequence':index,'interval_s':value}))
  api['apply_requested']()
  assert sys.getswitchinterval()==value
finally:
 sys.setswitchinterval(stock)
print('activation-and-restore-verified')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(HELPER)],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "activation-and-restore-verified" in result.stdout
    rows = [json.loads(line) for p in attest.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert [r["actual_s"] for r in rows] == [0.005, 0.0005, 0.0005, 0.005]
    assert len({r["pid"] for r in rows}) == 1 and all(r["gil_enabled"] for r in rows)
