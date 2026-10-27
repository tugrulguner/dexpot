"""Verify supported scheduler tracing on disposable CI; publish no process data."""

import argparse
import json
import os
import signal
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def run(command, output, timeout=60):
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        output.write_text(stdout + stderr)
        return process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        output.write_text("Capability command exceeded its fixed deadline.\n")
        return 124


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(exist_ok=False)
    safe = args.root / "public"
    safe.mkdir()
    result = {
        "scope": "supported System Trace capability, no benchmark, no security-setting changes",
        "raw_trace_uploaded": False,
    }
    for name, command in [
        ("version", ["xcrun", "xctrace", "version"]),
        ("templates", ["xcrun", "xctrace", "list", "templates"]),
        ("help-record", ["xcrun", "xctrace", "help", "record"]),
        ("help-export", ["xcrun", "xctrace", "help", "export"]),
    ]:
        result[name] = run(command, safe / (name + ".txt"))
    trace = args.root / "capability.trace"
    result["record_returncode"] = run(
        [
            "sudo",
            "-n",
            "xcrun",
            "xctrace",
            "record",
            "--template",
            "System Trace",
            "--all-processes",
            "--time-limit",
            "2s",
            "--no-prompt",
            "--output",
            str(trace),
        ],
        safe / "record.log",
        timeout=90,
    )
    if trace.exists():
        # Scope ownership strictly to this disposable job's generated trace.
        subprocess.run(
            ["sudo", "-n", "chown", "-R", str(os.getuid()) + ":" + str(os.getgid()), str(trace)],
            check=True,
        )
        result["toc_returncode"] = run(
            [
                "xcrun",
                "xctrace",
                "export",
                "--input",
                str(trace),
                "--toc",
                "--output",
                str(args.root / "toc-private.xml"),
            ],
            safe / "export.log",
        )
        if result["toc_returncode"] == 0:
            tree = ET.parse(args.root / "toc-private.xml")
            result["table_schemas"] = sorted(
                {n.attrib.get("schema", "") for n in tree.iter("table")}
            )
            # Only schemas/availability are public; no unrelated process rows.
    result["status"] = (
        "recorded-check-table-sufficiency"
        if result["record_returncode"] == 0 and result.get("toc_returncode") == 0
        else "capability-unavailable"
    )
    (safe / "capability.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
