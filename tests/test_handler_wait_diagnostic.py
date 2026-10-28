import importlib.util
import unittest
from pathlib import Path

S = importlib.util.spec_from_file_location(
    "cli", Path(__file__).resolve().parents[1] / "scripts/handler_wait_diagnostic/run.py"
)
assert S is not None and S.loader is not None
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


class Validation(unittest.TestCase):
    def fixture(self):
        return {
            "cell": {"id": "gil-mixed-1"},
            "runtime": {"pid": 5},
            "fingerprints": {"application": "a" * 64, "validator": "b" * 64, "wheel": "c" * 64},
            "metrics": {
                "io_good": 2,
                "good": 3,
                "bad": 0,
                "connect_errors": 0,
                "read_errors": 0,
                "write_errors": 0,
                "timeout_errors": 0,
            },
            "cleanup_pass": True,
            "client_returncode": 0,
            "wait_pid": 5,
            "requested_waits": [0.001],
            "wait_records": 2,
            "wait_drops": 0,
        }, {
            "pid": 5,
            "drops": 0,
            "records": [
                {"requested_secs": 0.001, "elapsed_ns": 3, "thread_cpu_ns": 1},
                {"requested_secs": 0.001, "elapsed_ns": 1, "thread_cpu_ns": 1},
            ],
        }

    def test_valid(self):
        m.validate(*self.fixture())

    def test_pid_mismatch(self):
        a, b = self.fixture()
        b["pid"] = 6
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_drops(self):
        a, b = self.fixture()
        b["drops"] = 1
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_wrong_wait(self):
        a, b = self.fixture()
        b["records"][0]["requested_secs"] = 0.002
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_missing(self):
        a, b = self.fixture()
        b["records"] = []
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_actual_serving_pid_not_metadata_only(self):
        a, b = self.fixture()
        a["wait_pid"] = 6
        b["pid"] = 6
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_missing_validator_fingerprint(self):
        a, b = self.fixture()
        del a["fingerprints"]["validator"]
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_native_timeout(self):
        a, b = self.fixture()
        a["metrics"]["timeout_errors"] = 1
        with self.assertRaises(ValueError):
            m.validate(a, b)

    def test_excess_inflight(self):
        a, b = self.fixture()
        b["records"] *= 10
        a["wait_records"] = len(b["records"])
        with self.assertRaises(ValueError):
            m.validate(a, b)


if __name__ == "__main__":
    unittest.main()
