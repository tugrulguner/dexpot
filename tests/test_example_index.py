"""Keep the runnable example index and installed-artifact checker complete."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_example_has_a_documented_start_command() -> None:
    readme = (ROOT / "examples" / "README.md").read_text()
    for example in (ROOT / "examples").glob("*.py"):
        assert f"uv run python examples/{example.name}" in readme, example.name


def test_installed_smoke_inventory_matches_real_examples() -> None:
    import runpy

    namespace = runpy.run_path(str(ROOT / "scripts" / "smoke_installed_examples.py"))
    assert namespace["EXPECTED_EXAMPLES"] == {
        path.name for path in (ROOT / "examples").glob("*.py")
    }


def test_installed_smoke_dispatches_every_example() -> None:
    import ast

    tree = ast.parse((ROOT / "scripts" / "smoke_installed_examples.py").read_text())
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    checked = {
        node.args[0].right.value
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith("_check_")
        and node.args
        and isinstance(node.args[0], ast.BinOp)
        and isinstance(node.args[0].right, ast.Constant)
    }
    assert checked == {path.name for path in (ROOT / "examples").glob("*.py")}
