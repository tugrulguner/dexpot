"""The policy adapter must not share mutable ctypes call metadata between workers."""

import threading
from concurrent.futures import ThreadPoolExecutor

from dexpot import _preparation_policy as module


def test_policy_call_wrappers_are_owned_by_each_thread(monkeypatch):
    calls = []
    lock = threading.Lock()

    class Function:
        def __init__(self, name):
            self.name = name

        def __call__(self, *args):
            if self.name == "pthread_self":
                return threading.get_ident()
            if self.name == "pthread_mach_thread_np":
                return args[0]
            with lock:
                calls.append((threading.get_ident(), self.name, self))
            if self.name == "thread_policy_get":
                args[2]._obj.value = 1
            return 0

    class Library:
        def __init__(self):
            self.cached = {}

        def __getattr__(self, name):
            if name not in self.cached:
                self.cached[name] = Function(name)
            return self.cached[name]

        def __getitem__(self, name):
            return Function(name)

    lib = Library()
    monkeypatch.setattr(module.ctypes, "CDLL", lambda path: lib)
    policy = module._DarwinPolicy()
    barrier = threading.Barrier(2)

    def run(_):
        barrier.wait()
        for _ in range(2):
            assert policy.current() == 1
            assert policy.set(0) == 0
        return threading.get_ident()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run, range(2)))
    assert first != second
    for name in ("thread_policy_get", "thread_policy_set"):
        left = [function for tid, kind, function in calls if tid == first and kind == name]
        right = [function for tid, kind, function in calls if tid == second and kind == name]
        assert len(left) == len(right) == 2
        assert left[0] is left[1]
        assert right[0] is right[1]
        assert left[0] is not right[0]
