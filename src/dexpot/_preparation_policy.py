"""Restore scheduling after a bounded preparation call, including failures."""

import ctypes
import sys
import threading


class _DarwinPolicy:
    def __init__(self):
        self.lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        self.lib.pthread_self.argtypes = []
        self.lib.pthread_self.restype = ctypes.c_void_p
        self.lib.pthread_mach_thread_np.argtypes = [ctypes.c_void_p]
        self.lib.pthread_mach_thread_np.restype = ctypes.c_uint
        self.lib.thread_policy_get.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.lib.thread_policy_get.restype = ctypes.c_int
        self.lib.thread_policy_set.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_uint,
        ]
        self.lib.thread_policy_set.restype = ctypes.c_int
        self.local = threading.local()

    def _state(self):
        if not hasattr(self.local, "state"):
            # Borrow the current pthread's port; do not create/leak a Mach right.
            self.local.state = (
                self.lib.pthread_mach_thread_np(self.lib.pthread_self()),
                ctypes.c_int(),
                ctypes.c_uint(1),
                ctypes.c_int(),
            )
        return self.local.state

    def current(self):
        port, value, count, default = self._state()
        count.value = 1
        default.value = 0
        result = self.lib.thread_policy_get(
            port, 1, ctypes.byref(value), ctypes.byref(count), ctypes.byref(default)
        )
        return -1 if result else value.value

    def set(self, enabled):
        port, value, _, _ = self._state()
        value.value = enabled
        return self.lib.thread_policy_set(port, 1, ctypes.byref(value), 1)


def darwin_policy():
    if sys.platform != "darwin":
        return None
    try:
        return _DarwinPolicy()
    except (OSError, AttributeError):
        return None


def scoped_preparer(prepare, policy):
    def checked(value):
        previous = policy.current()
        changed = previous == 1 and policy.set(0) == 0
        try:
            return prepare(value)
        finally:
            if changed and policy.set(previous) != 0:
                raise RuntimeError("could not restore worker scheduling policy")

    return checked
