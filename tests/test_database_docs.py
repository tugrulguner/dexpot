from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_database_example_is_documented_and_exercised_by_installed_smoke():
    for path in (ROOT / "tests/test_examples.py", ROOT / "scripts/smoke_installed_examples.py"):
        tree = ast.parse(path.read_text())
        inventory = next(
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "EXPECTED_EXAMPLES" for t in n.targets)
        )
        assert "database.py" in ast.literal_eval(inventory)
    smoke = ast.parse((ROOT / "scripts/smoke_installed_examples.py").read_text())
    main = next(n for n in smoke.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_check_database"
        for n in ast.walk(main)
    )
    assert "uv run python examples/database.py" in (ROOT / "examples/README.md").read_text()


def test_database_documentation_preserves_transaction_and_scope_boundaries():
    for name in (
        "examples/README.md",
        "src/dexpot/templates/skills/dexpot.md",
        "website/src/content/docs/route-contract.md",
    ):
        text = " ".join((ROOT / name).read_text().split()).lower()
        assert "database.py" in text
        assert "encoding failure after commit" in text
        assert "request-scoped dependency injection" in text
