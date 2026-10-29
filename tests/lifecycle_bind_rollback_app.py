"""Fresh-process driver for the bind-rollback ownership regression."""

from __future__ import annotations

import contextlib
import socket
import sys
import threading
from pathlib import Path

import pytest

from dexpot import Dex
from dexpot.app import _multiprocessing


def main(tmp_path: Path, cleanup_fails: bool, hold_exit: bool) -> None:
    app = Dex()
    cleanup_entered = _multiprocessing.Event()
    release_cleanup = _multiprocessing.Event()
    target_returned = _multiprocessing.Event()
    release_process_exit = _multiprocessing.Event()
    premature_retry = threading.Event()
    entered = _multiprocessing.Value("i", 0)
    trace = tmp_path / "events"
    original_socket = socket.socket

    class BindFailure(original_socket):
        def bind(self, address) -> None:
            raise OSError("controlled listener bind failure")

    def record(event: str) -> None:
        with trace.open("a") as stream:
            stream.write(event + "\n")

    @contextlib.contextmanager
    def resource():
        with entered.get_lock():
            entered.value += 1
            generation = entered.value
        record(f"enter-{generation}")
        if generation == 1:
            # Factory runs only in the forked child, not in the supervisor.
            socket.socket = BindFailure
        try:
            yield
        finally:
            if generation == 1:
                cleanup_entered.set()
                assert release_cleanup.wait(5), "test failed to release child cleanup"
            record(f"exit-{generation}")
            if cleanup_fails and generation == 1:
                raise RuntimeError("rollback cleanup sentinel")

    app.lifespan(resource)
    state = app._lifecycle
    channel = _multiprocessing.Queue()
    with original_socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    def first_target():
        state._worker_process("127.0.0.1", port, channel)
        if hold_exit:
            target_returned.set()
            assert release_process_exit.wait(5), "test failed to release native process exit"

    first = _multiprocessing.Process(target=first_target, daemon=True)
    new_worker = state._new_worker
    started = []
    coordinator = None

    def retry(*args):
        if not release_cleanup.is_set():
            premature_retry.set()
            raise AssertionError("replacement requested before prior resource cleanup")
        if first.exitcode is None:
            premature_retry.set()
            raise AssertionError("replacement requested before prior process exit")
        if coordinator is not None:
            coordinator.join(3)
            assert not coordinator.is_alive()
        return new_worker(*args)

    state._new_worker = retry  # type: ignore[method-assign]

    def release_after_observation():
        assert cleanup_entered.wait(3)
        # Give the original 0.2s join + 0.05s retry path an opportunity to
        # expose its overlap. This is a bounded race reproduction, not timing
        # evidence or an acceptance-budget change.
        premature_retry.wait(0.5)
        release_cleanup.set()
        if hold_exit:
            assert target_returned.wait(3)
            premature_retry.wait(0.5)
            release_process_exit.set()

    def track(proc):
        nonlocal coordinator
        started.append(proc)
        if coordinator is None:
            coordinator = threading.Thread(target=release_after_observation)
            coordinator.start()

    try:
        if cleanup_fails:
            with pytest.raises(
                RuntimeError, match=r"initialization failed.*rollback cleanup sentinel"
            ):
                state._start_ready_worker(
                    state, first, channel, "127.0.0.1", port, on_started=track
                )
            assert len(started) == 1, "cleanup failure was misclassified as retryable bind failure"
        else:
            replacement = state._start_ready_worker(
                state, first, channel, "127.0.0.1", port, on_started=track
            )
            assert replacement is not first
            records = trace.read_text().splitlines()
            assert records.index("exit-1") < records.index("enter-2")
        assert not premature_retry.is_set()
    finally:
        release_cleanup.set()
        release_process_exit.set()
        if coordinator is not None:
            coordinator.join(3)
        state._teardown(started)
        channel.close()
        channel.join_thread()
    assert all(not proc.is_alive() for proc in started)


if __name__ == "__main__":
    thread_errors: list[BaseException | None] = []
    threading.excepthook = lambda args: thread_errors.append(args.exc_value)
    main(Path(sys.argv[1]), sys.argv[2] == "1", sys.argv[3] == "1")
    assert not thread_errors, thread_errors
