"""Analyze four fixed interval windows without claiming baseline/candidate qualification."""

import argparse
import csv
import json
import re
import shutil
from pathlib import Path

from analyze_packet_markers import analyze


def quantile(values, q):
    values = sorted(values)
    return values[int((len(values) - 1) * q)] if values else None


def main(root):
    windows = json.loads((root / "windows.json").read_text())
    protocol = json.loads((root / "predeclared.json").read_text())
    plan = json.loads((root / "plan.json").read_text())
    assert len(windows) == 4 and len({w["pid"] for w in windows}) == 1
    assert protocol["gil_interval_order_s"] == [0.005, 0.0005, 0.0005, 0.005]
    server_rows = []
    server_drops = 0
    for f in (root / "markers").glob("*.jsonl"):
        for line in f.read_text().splitlines():
            row = json.loads(line)
            if "id" in row:
                server_rows.append((row, line))
            elif row.get("event") == "flush_summary":
                server_drops += row["dropped"]
    results = []
    for index, window in enumerate(windows):
        out = root / ("window-" + str(index))
        view = out / "analysis"
        view.mkdir()
        markers = view / "markers"
        markers.mkdir()
        pids = set()
        for f in (out / "markers").glob("client-*.jsonl"):
            match = re.fullmatch(r"client-([0-9]+)-[0-9]+\.jsonl", f.name)
            assert match
            pids.add(match.group(1))
            shutil.copy2(f, markers / f.name)
        assert len(pids) == 1
        with (markers / "server-derived.jsonl").open("w") as output:
            for row, line in server_rows:
                if row["id"].split("-")[0] in pids:
                    assert row["gil_switch_interval_s"] == protocol["gil_interval_order_s"][index]
                    output.write(line + "\n")
        packet = analyze(view, capture_root=out / "capture")
        pairs = list(csv.DictReader((view / "packet-pairs.csv").open()))
        footer = [
            json.loads(line.split(" ", 1)[1])
            for line in window["raw"]["stdout"].splitlines()
            if line.startswith("DIAG_SUMMARY ")
        ]
        totals = {
            k: sum(x[k] for x in footer)
            for k in ["prepared", "received", "pending", "dropped", "clock_errors", "unmatched"]
        }
        m = window["raw"]["metrics"]
        valid = (
            window["checks_pass"]
            and packet["capture_zero_drop_verified"]
            and packet["packet_unknowns"] == []
            and not any(
                packet["packet_counts"][k]
                for k in ["truncated_packets", "conflicting_bytes", "gapped_streams"]
            )
            and len(footer) == 4
            and not any(totals[k] for k in ["dropped", "clock_errors", "unmatched"])
            and len(pairs) == totals["received"]
            and server_drops == 0
        )
        results.append(
            {
                "index": index,
                "mode": window["mode"],
                "interval_s": protocol["gil_interval_order_s"][index],
                "valid_for_interval_diagnostic": valid,
                "native_metrics": m,
                "goodput": m["good"] * 1e6 / m["duration_us"],
                "marker_totals": totals,
                "matched": len(pairs),
                "packet_count": packet["packet_counts"]["capture_packets"],
                "server_tap_to_parsed_sample_p99_us": quantile(
                    [float(x["server_request_tap_to_parsed_us"]) for x in pairs], 0.99
                ),
                "server_tap_to_parsed_ge_10ms_count": sum(
                    float(x["server_request_tap_to_parsed_us"]) >= 10000 for x in pairs
                ),
                "packet_slow_classes": packet["slow_dominant_80pct_counts"],
            }
        )
    comparisons = []
    for stock_index, short_index in [(0, 1), (3, 2)]:
        stock, short = results[stock_index], results[short_index]
        gr = short["goodput"] / stock["goodput"]
        pr = short["native_metrics"]["p99_us"] / stock["native_metrics"]["p99_us"]
        sr = (
            short["server_tap_to_parsed_sample_p99_us"]
            / stock["server_tap_to_parsed_sample_p99_us"]
        )
        comparisons.append(
            {
                "stock_index": stock_index,
                "short_index": short_index,
                "direction": "short/stock",
                "goodput_ratio": gr,
                "native_p99_ratio": pr,
                "server_sample_p99_ratio": sr,
                "original_numeric_limits_only_pass": gr >= plan["comparison"]["min_goodput_ratio"]
                and pr <= plan["comparison"]["max_adjusted_p99_ratio"],
            }
        )
    all_valid = all(x["valid_for_interval_diagnostic"] for x in results)
    nonoverlap = all_valid and max(
        results[i]["server_tap_to_parsed_sample_p99_us"] for i in [1, 2]
    ) < min(results[i]["server_tap_to_parsed_sample_p99_us"] for i in [0, 3])
    final = {
        "status": "interval-sensitivity-supported-in-this-diagnostic"
        if nonoverlap
        else "interval-mechanism-not-established",
        "scope": "four dependent same-PID diagnostic windows, not independent baseline recordings or feature qualification",
        "windows": results,
        "comparisons": comparisons,
        "all_valid": all_valid,
        "both_short_windows_below_both_stock_server_sample_p99": nonoverlap,
        "server_drops": server_drops,
        "qualified": False,
        "limits": "Four ordered windows and periodic samples do not establish a unique historical root cause. Switch interval can affect interactions with OS/VM scheduling. No global library tuning or native/runtime PR change is justified by this diagnostic alone.",
    }
    (root / "gil-handoff-analysis.json").write_text(json.dumps(final, indent=2))
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root)
