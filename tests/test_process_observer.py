from __future__ import annotations

import contextlib
import runpy
import select
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts/lifecycle_preflight_harness"


def test_snapshot_uses_explicit_child_observer_without_global_scan():
    api = runpy.run_path(str(ROOT / "run.py"))

    def forbidden():
        raise AssertionError("repeated global process scan")

    process = SimpleNamespace(
        oneshot=contextlib.nullcontext,
        cpu_times=lambda: SimpleNamespace(user=1, system=2),
        memory_info=lambda: SimpleNamespace(rss=512),
        num_threads=lambda: 17,
        num_fds=lambda: 20,
        children=forbidden,
    )
    observer = SimpleNamespace(children=lambda p: 1)
    snapshot = api["snapshot"](process, observer)
    assert snapshot["children"] == 1
    assert snapshot["cpu"] == 3 and snapshot["threads"] == 17


def test_observer_cleanup_attempts_every_descriptor_even_after_error():
    api = runpy.run_path(str(ROOT / "process_observer.py"))
    observer = api["ChildrenObserver"]()
    events = []

    def fail():
        events.append("failed")
        raise RuntimeError("close failed")

    observer.guards = {
        1: SimpleNamespace(close=lambda: events.append("first")),
        2: SimpleNamespace(close=fail),
    }
    with pytest.raises(RuntimeError, match="close failed"):
        observer.close()
    assert events == ["failed", "first"]


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin kernel process events")
def test_kernel_guard_detects_child_that_exited_between_samples():
    api = runpy.run_path(str(ROOT / "process_observer.py"))
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; sys.stdin.readline(); subprocess.run([sys.executable,'-c','pass'],check=True); print('done',flush=True); sys.stdin.readline()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    guard = None
    try:
        guard = api["ForkGuard"](process.pid)
        assert guard.count() == 0
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write("go\n")
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline().strip() == "done"
        assert guard.count() == 1
        assert guard.count() == 1, "transient-child violation must remain sticky"
    finally:
        if guard is not None:
            guard.close()
        process.terminate()
        process.wait(timeout=3)


def test_other_platform_preserves_polling(monkeypatch):
    api = runpy.run_path(str(ROOT / "process_observer.py"))
    monkeypatch.setattr(sys, "platform", "linux")
    observer = api["ChildrenObserver"]()
    assert observer.children(SimpleNamespace(children=lambda: [object()])) == 1
    observer.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin kernel process events")
@pytest.mark.parametrize("pid", [-1, 2147483647])
def test_failed_guard_registration_does_not_leak_descriptors(pid):
    import psutil

    api = runpy.run_path(str(ROOT / "process_observer.py"))
    own = psutil.Process()
    before = own.num_fds()
    for _ in range(10):
        with pytest.raises((OSError, OverflowError, ValueError, psutil.NoSuchProcess)):
            api["ForkGuard"](pid)
    assert own.num_fds() == before


def test_native_fingerprints_include_observer_source():
    api = runpy.run_path(str(ROOT / "run.py"))
    args = SimpleNamespace(
        plan=ROOT / "plan.json", wrk=ROOT / "validate.lua", wheel=ROOT / "application.py"
    )
    hashes = api["fingerprints"](args)
    assert hashes["process_observer"] == api["sha"](ROOT / "process_observer.py")
