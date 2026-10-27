import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_window_scope_keeps_real_server_and_defers_cleanup(tmp_path):
    python = os.environ.get("SEED_PROBE_TEST_PYTHON")
    if python is None:
        pytest.skip("explicit installed consumer interpreter required")
    api = runpy.run_path(str(ROOT / "scripts/lifecycle_preflight_harness/run.py"))
    diagnostic = runpy.run_path(str(ROOT / "scripts/persistent_gil_context_probe.py"))
    env = dict(
        os.environ,
        DEXPOT_WORKERS="1",
        DEXPOT_POOL="16",
        DEXPOT_MAX_QUEUE="16",
        DEXPOT_MAX_CONNECTIONS="32",
        PYTHONHASHSEED="1",
    )
    env.pop("PYTHON_GIL", None)
    env.pop("PYTHONPATH", None)
    with api["server"](python, env, tmp_path / "outer.log") as (process, port, state):
        scope = diagnostic["shared_server"](api, process, port, state)
        for index in range(2):
            with scope(python, env, tmp_path / ("window-" + str(index) + ".log")) as (
                observed,
                seen_port,
                seen_state,
            ):
                assert observed.pid == process.pid
                assert seen_port == port and seen_state is state
                assert api["request"](seen_port, "/flat") == (200, api["FLAT"])
            assert process.poll() is None
            assert state["cleanup_pass"] is False
    assert state["cleanup_pass"] is True


def test_dead_persistent_server_is_not_replaced(tmp_path):
    diagnostic = runpy.run_path(str(ROOT / "scripts/persistent_gil_context_probe.py"))

    class Exited:
        def poll(self):
            return 0

    scope = diagnostic["shared_server"]({}, Exited(), 0, {})
    with pytest.raises(RuntimeError, match="exited"), scope("unused", {}, tmp_path / "unused.log"):
        pytest.fail("dead server must not enter a window")
