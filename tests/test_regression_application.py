"""Real HTTP contracts for the diagnostic benchmark fixture, not performance tests."""

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "benchmarks/regression/application.py"


def test_benchmark_fixture_serves_checked_flat_nested_and_actual_runtime(tmp_path):
    assert APP.exists(), "the bounded screen needs an executable HTTP fixture"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEXPOT_")}
    env.update(DEXPOT_WORKERS="1", DEXPOT_HTTP_PARSER="python")
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(APP), "--port", str(port)], env=env, stdout=log, stderr=log
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    conn.request("GET", "/runtime")
                    response = conn.getresponse()
                    identity = json.loads(response.read())
                    conn.close()
                    assert response.status == 200
                    break
                except OSError:
                    assert process.poll() is None, (tmp_path / "server.log").read_text()
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
            assert identity["gil_enabled"] is getattr(sys, "_is_gil_enabled", lambda: True)()
            assert identity["selected_ft"] is (not identity["gil_enabled"])
            assert identity["parser"] == "python"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            for route in ("flat", "cpu", "io", "nested"):
                conn.request("GET", "/" + route)
                response = conn.getresponse()
                body = json.loads(response.read())
                assert response.status == 200
                if route == "nested":
                    assert body["title"] == "group" and len(body["items"]) == 16
                    assert body["items"][15] == {"id": 15, "name": "item-15", "price": 9.99}
                else:
                    assert body == {"id": 7, "name": "item-7", "price": 9.99}
            conn.close()
            if wrk := shutil.which("wrk"):
                client = APP.with_name("validate.lua")
                assert client.exists(), "native load must validate every timed response"
                for profile in ("flat", "nested", "mixed"):
                    command = [
                        wrk,
                        "-t4",
                        "-c16",
                        "-d1s",
                        "-s",
                        str(client),
                        f"http://127.0.0.1:{port}",
                        "--",
                        profile,
                    ]
                    output = subprocess.check_output(command, text=True, timeout=10)
                    line = next(s for s in output.splitlines() if s.startswith("METRICS "))
                    metrics = json.loads(line.removeprefix("METRICS "))
                    assert metrics["good"] == metrics["requests"] > 0
                    assert metrics["bad"] == 0
                poisoned = tmp_path / "poisoned.lua"
                poisoned.write_text(client.read_text().replace("item-7", "wrong-7"))
                command[command.index(str(client))] = str(poisoned)
                output = subprocess.check_output(command, text=True, timeout=10)
                line = next(s for s in output.splitlines() if s.startswith("METRICS "))
                assert json.loads(line.removeprefix("METRICS "))["bad"] > 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise
        assert process.returncode == (1 if os.name == "nt" else 0)
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
