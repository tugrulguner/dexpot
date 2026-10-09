import sys
from typing import Any, cast

import pytest

from dexpot._preparation_policy import scoped_preparer


class Policy:
    def __init__(self):
        self.value = 1
        self.events = []

    def current(self):
        return self.value

    def set(self, value):
        self.events.append(value)
        self.value = value
        return 0


def test_preparation_only_is_protected():
    p = Policy()

    def prepare(value):
        assert p.value == 0
        return value

    wrapped = scoped_preparer(prepare, p)
    assert wrapped("out") == "out"
    assert p.value == 1
    assert p.events == [0, 1]


def test_exception_restores_original_policy():
    p = Policy()

    def prepare(value):
        raise ValueError("bad output")

    with pytest.raises(ValueError, match="bad output"):
        scoped_preparer(prepare, p)(None)
    assert p.value == 1
    assert p.events == [0, 1]


def test_already_fixed_policy_is_preserved():
    p = Policy()
    p.value = 0
    assert scoped_preparer(lambda value: value, p)(42) == 42
    assert p.value == 0
    assert p.events == []


def test_failed_policy_change_does_not_skip_validation():
    p = Policy()

    def failed(value):
        p.events.append(value)
        return 5

    p.set = failed  # pyright: ignore[reportAttributeAccessIssue]
    calls = []
    assert scoped_preparer(lambda value: calls.append(value) or value, p)(42) == 42
    assert calls == [42]
    assert p.value == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin native adapter")
def test_native_adapter_changes_only_current_thread():
    import threading

    from dexpot import _preparation_policy as module

    policy = module.darwin_policy()
    assert policy is not None
    assert policy.current() == 1
    seen = []

    def run():
        def prepare(value):
            seen.append(policy.current())
            return value

        assert scoped_preparer(prepare, policy)(42) == 42
        seen.append(policy.current())

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert seen == [0, 1]
    assert policy.current() == 1


def test_ft_nested_compiler_uses_scoped_guard(monkeypatch):
    import sys

    import msgspec

    from dexpot import _preparation_policy as module
    from dexpot._plans import _checked_fallback
    from dexpot._response import compile_preparer

    if getattr(sys, "_is_gil_enabled", lambda: True)():
        pytest.skip("FT integration")

    class Item(msgspec.Struct):
        value: int

    class Nested(msgspec.Struct):
        items: list[Item]

    p = Policy()
    monkeypatch.setattr(module, "darwin_policy", lambda: p)
    prepare = compile_preparer(Nested, _checked_fallback)
    assert p.events == []
    assert prepare(Nested([Item(1)])) is not None
    assert p.events == [0, 1]
    assert p.current() == 1
    p.events.clear()
    with pytest.raises((ValueError, TypeError)):
        prepare(Nested([Item(cast(Any, "bad"))]))
    assert p.events == [0, 1]
    assert p.current() == 1


def test_gil_routes_use_unchanged_compiler():
    import sys

    import dexpot._plans as plans

    if not getattr(sys, "_is_gil_enabled", lambda: True)():
        pytest.skip("GIL preservation")
    assert plans.compile_preparer.__module__ == "dexpot._response_legacy"


def test_unknown_policy_does_not_bypass_preparation():
    p = Policy()
    p.value = -1
    calls = []
    assert scoped_preparer(lambda value: calls.append(value) or value, p)(42) == 42
    assert calls == [42]
    assert p.events == []


@pytest.mark.parametrize("validation_fails", [False, True])
def test_restore_failure_is_reported_with_validation_context(validation_fails):
    p = Policy()

    def setter(value):
        p.events.append(value)
        if value == 1:
            return 5
        p.value = value
        return 0

    p.set = setter  # pyright: ignore[reportAttributeAccessIssue]

    def prepare(value):
        if validation_fails:
            raise ValueError("validation failed")
        return value

    with pytest.raises(RuntimeError, match="could not restore") as caught:
        scoped_preparer(prepare, p)(42)
    assert p.events == [0, 1]
    if validation_fails:
        assert isinstance(caught.value.__context__, ValueError)
    else:
        assert caught.value.__context__ is None
