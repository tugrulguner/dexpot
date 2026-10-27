import ast
import json
import os
import runpy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def helper_source():
    tree = ast.parse((ROOT / "scripts/hash_seed_context_probe.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assignment = next(
        n
        for n in main.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "helper" for t in n.targets)
    )
    return ast.literal_eval(assignment.value)


def test_context_collector_writes_parseable_real_counters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = {}
    exec(compile(helper_source(), "<context-helper>", "exec"), namespace)
    namespace["record_context"]()
    namespace["record_context"]()
    path = tmp_path / "context-probes" / (str(os.getpid()) + ".jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert all(
        r["pid"] == os.getpid() and r["hash_randomization"] == sys.flags.hash_randomization
        for r in rows
    )
    for key in ["user_cpu_s", "system_cpu_s", "voluntary_switches", "involuntary_switches"]:
        assert rows[1][key] >= rows[0][key] >= 0


@pytest.mark.parametrize("seed", ["0", "1"])
def test_real_server_seed_attestation_preserves_runtime_response(tmp_path, seed):
    python = os.environ.get("SEED_PROBE_TEST_PYTHON")
    if python is None:
        pytest.skip("installed standard interpreter consumer supplied explicitly")
    original = ROOT / "scripts/lifecycle_preflight_harness"
    harness = tmp_path / "harness"
    shutil.copytree(original, harness)
    app = harness / "application.py"
    source = (
        app.read_text()
        .replace("import sys\n", "import sys\nfrom context_sidecar import record_context\n", 1)
        .replace("def runtime() -> dict:\n", "def runtime() -> dict:\n    record_context()\n", 1)
    )
    app.write_text(source)
    (harness / "context_sidecar.py").write_text(helper_source())
    api = runpy.run_path(str(harness / "run.py"))
    folder = tmp_path / "consumer"
    folder.mkdir()
    env = dict(
        os.environ,
        PYTHONHASHSEED=seed,
        DEXPOT_WORKERS="1",
        DEXPOT_POOL="16",
        DEXPOT_MAX_QUEUE="32",
        DEXPOT_MAX_CONNECTIONS="32",
    )
    env.pop("PYTHON_GIL", None)
    env.pop("PYTHONPATH", None)
    with api["server"](python, env, folder / "server.log") as (process, port, state):
        status, body = api["request"](port, "/runtime")
        before = json.loads(body)
        assert status == 200
        status, body = api["request"](port, "/flat")
        assert status == 200 and json.loads(body) == {"id": 7, "name": "item-7", "price": 9.99}
        status, body = api["request"](port, "/runtime")
        assert status == 200 and json.loads(body) == before
    assert state["cleanup_pass"]
    rows = [
        json.loads(line)
        for line in (folder / "context-probes" / (str(process.pid) + ".jsonl"))
        .read_text()
        .splitlines()
    ]
    assert len(rows) >= 2 and all(
        r["seed"] == seed and r["hash_randomization"] == int(seed != "0") and r["gil_enabled"]
        for r in rows
    )
