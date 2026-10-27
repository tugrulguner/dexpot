"""Bounded tests, never invoke the profiler or sudo on the personal host."""

import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "trace_cap", Path(__file__).parents[1] / "scripts/system_trace_capability.py"
)
assert SPEC is not None and SPEC.loader is not None
CAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAP)


def test_capture_actual_child_output(tmp_path):
    output = tmp_path / "output"
    assert CAP.run([sys.executable, "-c", 'print("owned child")'], output) == 0
    assert output.read_text().strip() == "owned child"


def test_own_process_deadline(tmp_path):
    output = tmp_path / "output"
    assert (
        CAP.run([sys.executable, "-c", "import time; time.sleep(10)"], output, timeout=0.05) == 124
    )
    assert "deadline" in output.read_text()


def test_private_toc_rows_not_published(tmp_path, monkeypatch):
    root = tmp_path / "trace"

    def fake_run(command, output, timeout=60):
        output.write_text("synthetic unit-test tool result\n")
        if "record" in command and "--output" in command:
            Path(command[command.index("--output") + 1]).mkdir()
        if "--toc" in command:
            Path(command[command.index("--output") + 1]).write_text(
                '<trace-toc><run><info><process>private-unit-test-name</process></info><data><table schema="unit-test-only"/></data></run></trace-toc>'
            )
        return 0

    monkeypatch.setattr(CAP, "run", fake_run)
    monkeypatch.setattr(CAP.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["probe", "--root", str(root)])
    CAP.main()
    assert "private-unit-test-name" not in "".join(
        p.read_text() for p in (root / "public").iterdir()
    )
    assert "unit-test-only" in (root / "public/capability.json").read_text()
