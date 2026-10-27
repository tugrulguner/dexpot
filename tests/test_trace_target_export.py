"""Synthetic XML fixtures test filtering only, never substitute for real traces."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "target_export", Path(__file__).parents[1] / "scripts/trace_target_export.py"
)
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


def test_target_refs_and_foreign_redaction(tmp_path):
    source, destination = tmp_path / "in.xml", tmp_path / "out.jsonl"
    source.write_text("""<trace-query-result><schema name="unit-test-only"/><node>
    <row><thread id="1"><tid>33</tid><process id="2" pid="100" fmt="owned (100)"/></thread><state>Running</state></row>
    <row><thread ref="1"/><state>Runnable</state><thread><process pid="999" fmt="private foreign"/></thread></row>
    <row><thread><process pid="999" fmt="private foreign"/></thread></row>
    </node></trace-query-result>""")
    result = EXPORT.filter_table(source, destination, {100})
    assert result["total_rows"] == 3 and result["target_rows"] == 2
    assert result["unresolved_references"] == 0
    public = destination.read_text()
    assert "Runnable" in public and "Running" in public
    assert "private foreign" not in public and "999" not in public


def test_unresolved_ownership_cannot_be_promoted(tmp_path):
    source, destination = tmp_path / "in.xml", tmp_path / "out.jsonl"
    source.write_text('<root><row><thread ref="missing"/></row></root>')
    result = EXPORT.filter_table(source, destination, {100})
    assert result["target_rows"] == 0 and result["unresolved_references"] == 1
    assert destination.read_text() == ""
