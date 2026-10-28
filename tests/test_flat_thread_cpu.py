import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="read-only Darwin CPU counters")


def load_clock():
    path = Path(__file__).resolve().parents[1] / "scripts/flat_thread_cpu/collector/thread_clock.py"
    spec = importlib.util.spec_from_file_location("validated_thread_clock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_thread_identity_and_nonnegative_cpu():
    clock = load_clock()
    result = clock.read(threading.current_thread())
    assert result["native_id"] == threading.get_native_id()
    assert result["user_ns"] >= 0 and result["system_ns"] >= 0


def test_wrong_native_identity_fails_closed():
    clock = load_clock()
    current = threading.current_thread()
    assert current.native_id is not None
    wrong = SimpleNamespace(
        is_alive=lambda: True, ident=current.ident, native_id=current.native_id + 1, name="wrong"
    )
    with pytest.raises(RuntimeError, match="identity mismatch"):
        clock.read(wrong)


def test_missing_fixed_owner_fails_closed():
    clock = load_clock()
    with pytest.raises(RuntimeError, match="pool mismatch"):
        clock.snapshot(None, object())
