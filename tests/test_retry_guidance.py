from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scalar_client_examples_show_conflicting_and_identical_repeats():
    for relative in (
        "examples/typed_inputs.py",
        "examples/README.md",
        "website/src/content/docs/guides/typed-api.md",
    ):
        text = (ROOT / relative).read_text()
        assert "limit=1&limit=2" in text, relative
        assert "limit=1&limit=1" in text, relative
        assert "query parameter 'limit': repeated" in text, relative


def test_database_retry_guidance_explains_reuse_conflict_and_transaction_boundary():
    for relative in (
        "examples/README.md",
        "website/src/content/docs/route-contract.md",
        "src/dexpot/templates/skills/dexpot.md",
    ):
        text = " ".join((ROOT / relative).read_text().split())
        for required in (
            "/retry-safe/items",
            "--retry-demo",
            "same operation ID",
            "409",
            "same database transaction",
        ):
            assert required in text, (relative, required)
