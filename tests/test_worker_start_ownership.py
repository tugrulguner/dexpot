from __future__ import annotations

import pytest

from dexpot._lifecycle import LifecycleRunner
from dexpot.app import Dex


class Worker:
    def __init__(self, name: str, starts: list[str]) -> None:
        self.name = name
        self.starts = starts

    def start(self) -> None:
        self.starts.append(self.name)

    def join(self, timeout: float | None = None) -> None:
        pass


class Channel:
    def __init__(self) -> None:
        self.results = iter([("bind_error", "busy"), RuntimeError("channel broke")])

    def get(self, timeout: float) -> tuple[str, str]:
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_retry_replacement_is_registered_before_readiness_wait_can_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[str] = []
    first = Worker("first", starts)
    replacement = Worker("replacement", starts)
    owner = LifecycleRunner(Dex())
    owner._new_worker = lambda *args: replacement  # type: ignore[method-assign]
    owned = [first]

    def register_started(proc: Worker) -> None:
        owned[0] = proc

    with pytest.raises(RuntimeError, match="did not acknowledge readiness"):
        LifecycleRunner._start_ready_worker(
            owner, first, Channel(), "127.0.0.1", 1, on_started=register_started
        )

    assert starts == ["first", "replacement"]
    assert owned[0] is replacement
