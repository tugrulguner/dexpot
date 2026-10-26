from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.name != "posix"
    or not hasattr(socket, "SO_REUSEPORT")
    or not getattr(sys, "_is_gil_enabled", lambda: True)(),
    reason="GIL multiprocess resource rollback requires POSIX fork",
)
@pytest.mark.parametrize("cleanup_fails,hold_exit", [(False, False), (False, True), (True, False)])
def test_bind_retry_waits_for_resource_rollback_and_process_exit(
    tmp_path, cleanup_fails, hold_exit
) -> None:
    # Fork only in a fresh supervisor, never in the pytest process after other
    # tests/coverage plugins have started threads.
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), DEXPOT_POOL="2", DEXPOT_MAX_QUEUE="2")
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tests/lifecycle_bind_rollback_app.py"),
            str(tmp_path),
            str(int(cleanup_fails)),
            str(int(hold_exit)),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
