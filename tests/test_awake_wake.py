import importlib
import queue
import threading
from types import SimpleNamespace


def bare_owner():
    module = importlib.import_module("dexpot._gil_io")
    owner = module.SocketIO.__new__(module.SocketIO)
    owner._lock = threading.Lock()
    owner._commands = queue.SimpleQueue()
    owner._wake_pending = False
    owner._stopping = False
    owner._awake_coalescing = True
    owner._sleeping = False
    calls = []
    owner._wake = lambda: calls.append("wake")
    return owner, calls


def test_awake_owner_does_not_need_producer_socket_wakeup():
    owner, calls = bare_owner()
    owner._submit(None, "register", None, None)
    assert calls == [], "producer used native wake while the owner is awake"
    assert owner._commands.qsize() == 1


def test_publish_sleep_before_selection_so_a_racing_producer_wakes():
    owner, calls = bare_owner()
    seen = []

    def select(timeout):
        assert owner._sleeping
        producer = threading.Thread(
            target=lambda: owner._submit(None, "register", None, None), daemon=True
        )
        producer.start()
        producer.join(0.5)
        assert not producer.is_alive(), "selector held producer lock"
        seen.append(timeout)
        return ["ready"]

    owner._selector = SimpleNamespace(select=select)
    assert callable(getattr(owner, "_poll", None)), "no atomic pre-select sleep publication"
    assert owner._poll(0.5) == ["ready"]
    assert seen == [0.5] and calls == ["wake"] and not owner._sleeping


def test_commands_queued_before_selection_force_one_nonblocking_readiness_turn():
    owner, calls = bare_owner()
    owner._submit(None, "register", None, None)
    seen = []

    def select(timeout):
        seen.append(timeout)
        assert not owner._sleeping
        return ["ready"]

    owner._selector = SimpleNamespace(select=select)
    assert callable(getattr(owner, "_poll", None)), "queued command has no pre-select guard"
    assert owner._poll(0.5) == ["ready"]
    assert seen == [0] and calls == []
    serviced = []
    owner._advance = lambda task: serviced.append(task)
    owner._drain_commands()
    assert len(serviced) == 1 and owner._commands.empty()


def test_non_darwin_keeps_legacy_enqueue_wakeup_and_select_timeout():
    owner, calls = bare_owner()
    owner._awake_coalescing = False
    owner._submit(None, "register", None, None)
    seen = []
    owner._selector = SimpleNamespace(select=lambda timeout: seen.append(timeout) or [])
    assert calls == ["wake"]
    assert callable(getattr(owner, "_poll", None))
    assert owner._poll(0.5) == [] and seen == [0.5]
