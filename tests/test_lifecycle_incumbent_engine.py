"""Keep optional lifecycle management outside the incumbent connection engine.

The fixture contains normalized-AST fingerprints from frozen main ca4979a,
not from the failed lifecycle candidate. These are architectural invariants,
not a substitute for real HTTP or performance qualification.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

from dexpot import Dex

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "lifecycle-incumbent-ast.json").read_text()
)


def canonical_ast(node: object) -> object:
    # ast.dump formatting and optional-empty defaults differ across supported
    # Python versions. Normalize actual fields, excluding empty type parameters
    # introduced after Python 3.11, rather than hashing presentation output.
    if isinstance(node, ast.AST):
        return [
            type(node).__name__,
            [
                [key, canonical_ast(value)]
                for key, value in ast.iter_fields(node)
                if key != "type_params" or value
            ],
        ]
    if isinstance(node, list):
        return [canonical_ast(value) for value in node]
    return [type(node).__name__, repr(node)]


def test_incumbent_constructor_and_connection_engine_are_unchanged() -> None:
    source_file = inspect.getsourcefile(Dex)
    assert source_file is not None
    module = ast.parse(Path(source_file).read_text())
    cls = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Dex"
    )
    functions = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    for name, expected in FIXTURE["methods"].items():
        actual = hashlib.sha256(json.dumps(canonical_ast(functions[name])).encode()).hexdigest()
        assert actual == expected, (
            f"incumbent {name} changed; lifecycle must stay outside this path"
        )


def test_unused_application_has_no_additional_instance_state() -> None:
    assert sorted(vars(Dex())) == FIXTURE["constructor_fields"]


def test_unused_application_does_not_load_lifecycle_engine() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from dexpot import Dex; app = Dex(); "
            "assert 'dexpot._lifecycle' not in sys.modules",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
