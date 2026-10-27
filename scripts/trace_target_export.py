"""Export only target-owned rows; retain unresolved references as explicit unknowns."""

import copy
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import OrderedDict


class References:
    def __init__(self, limit=100000):
        self.items = OrderedDict()
        self.limit = limit
        self.unresolved = 0

    def remember(self, node):
        for element in node.iter():
            if "id" in element.attrib:
                key = element.attrib["id"]
                self.items[key] = copy.deepcopy(element)
                self.items.move_to_end(key)
                if len(self.items) > self.limit:
                    self.items.popitem(last=False)

    def expand(self, node, seen=frozenset()):
        if "ref" in node.attrib:
            key = node.attrib["ref"]
            if key in seen:
                return ET.Element("reference-cycle")
            if key not in self.items:
                self.unresolved += 1
                return ET.Element("unresolved-reference", {"ref": key})
            source = self.items[key]
            self.items.move_to_end(key)
            return self.expand(source, seen | {key})
        result = ET.Element(node.tag, dict(node.attrib))
        result.text = node.text
        for child in node:
            result.append(self.expand(child, seen))
        return result


def pids(node):
    found = set()
    for element in node.iter():
        for key in ("pid", "process-id"):
            value = element.attrib.get(key, "")
            if value.isdigit():
                found.add(int(value))
        if element.tag in ("pid", "process-id") and (element.text or "").isdigit():
            found.add(int(element.text))
        if element.tag == "process":
            match = re.search(r"\((\d+)\)$", element.attrib.get("fmt", ""))
            if match:
                found.add(int(match.group(1)))
    return found


def redact_foreign(node, targets):
    # Remove an entire non-target process/thread subtree, including its labels.
    if node.tag in ("process", "thread") and (not pids(node) or not pids(node) <= targets):
        return ET.Element("unrelated-target-redacted")
    result = ET.Element(node.tag, dict(node.attrib))
    result.text = node.text
    for child in node:
        result.append(redact_foreign(child, targets))
    return result


def filter_table(source, destination, targets):
    refs = References()
    counts = {"total_rows": 0, "target_rows": 0, "unresolved_references": 0}
    schema = None
    stack = []
    with destination.open("w") as output:
        for event, node in ET.iterparse(source, events=("start", "end")):
            if event == "start":
                stack.append(node)
                continue
            if node.tag == "schema":
                schema = ET.tostring(node, encoding="unicode")
                output.write(json.dumps({"schema_xml": schema}) + "\n")
            if node.tag == "row":
                counts["total_rows"] += 1
                refs.remember(node)
                expanded = refs.expand(node)
                own = pids(expanded) & targets
                if own:
                    counts["target_rows"] += 1
                    output.write(
                        json.dumps(
                            {
                                "pids": sorted(own),
                                "row_xml": ET.tostring(
                                    redact_foreign(expanded, targets), encoding="unicode"
                                ),
                            }
                        )
                        + "\n"
                    )
                if len(stack) >= 2:
                    stack[-2].remove(node)
                node.clear()
            stack.pop()
    counts["unresolved_references"] = refs.unresolved
    counts["schema_present"] = schema is not None
    return counts


def export_targets(trace, private, public, targets):
    private.mkdir()
    public.mkdir()
    toc = private / "toc.xml"
    subprocess.run(
        ["xcrun", "xctrace", "export", "--input", str(trace), "--toc", "--output", str(toc)],
        check=True,
        timeout=180,
    )
    available = {n.attrib.get("schema") for n in ET.parse(toc).iter("table")}
    result = {}
    for schema in [
        "thread-state",
        "context-switch",
        "syscall",
        "time-profile",
        "time-sample",
        "life-cycle-period",
    ]:
        if schema not in available:
            result[schema] = {"status": "unavailable"}
            continue
        raw = private / (schema + ".xml")
        command = [
            "xcrun",
            "xctrace",
            "export",
            "--input",
            str(trace),
            "--xpath",
            '/trace-toc/run[@number="1"]/data/table[@schema="' + schema + '"]',
            "--output",
            str(raw),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=180
        )
        if completed.returncode != 0:
            result[schema] = {"status": "export-failed", "returncode": completed.returncode}
            continue
        result[schema] = filter_table(raw, public / (schema + ".jsonl"), targets)
    (public / "availability.json").write_text(json.dumps(result, indent=2))
    return result
