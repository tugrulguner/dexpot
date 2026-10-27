"""Join actual matched markers; report boundary localization, never scheduler causality."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

EVENTS = ["Crequest_prepared", "Sparsed", "Ssend_entry", "Ssend_return", "Cresponse_callback_entry"]


def analyze(root):
    events = defaultdict(lambda: defaultdict(list))
    server_dropped = 0
    for path in sorted((root / "markers").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if "id" in row:
                events[row["id"]][row["event"]].append(row)
            elif row.get("event") == "flush_summary":
                server_dropped += row["dropped"]
    windows = json.loads((root / "windows.json").read_text())
    summaries = [
        json.loads(line.split(" ", 1)[1])
        for line in windows[1]["raw"]["stdout"].splitlines()
        if line.startswith("DIAG_SUMMARY ")
    ]
    diagnostics = {
        key: sum(r[key] for r in summaries)
        for key in ["prepared", "received", "pending", "dropped", "clock_errors", "unmatched"]
    }
    invalid = Counter()
    pairs = []
    for ident, buckets in sorted(events.items()):
        if any(len(buckets.get(event, [])) != 1 for event in EVENTS):
            invalid["missing_or_duplicate_boundary"] += 1
            continue
        e = {event: buckets[event][0] for event in EVENTS}
        if any(type(e[k].get("wall_us")) is not int for k in EVENTS):
            invalid["missing_clock"] += 1
            continue
        c0, s0, s1, s2, c1 = [e[k]["wall_us"] for k in EVENTS]
        if c0 > s0 + 2 or s0 > s1 or s1 > c1 + 2 or c1 < c0 or s2 < s1:
            invalid["boundary_order_or_cross_clock_anomaly"] += 1
            continue
        wall = s1 - s0
        mono = (e["Ssend_entry"]["mono_ns"] - e["Sparsed"]["mono_ns"]) / 1000
        if abs(wall - mono) > 100:
            invalid["wall_mono_disagreement_over_100us_unknown_clock_or_sampling_skew"] += 1
            continue
        total = c1 - c0
        if total <= 0:
            invalid["nonpositive_callback_interval"] += 1
            continue
        segments = {
            "preparse_us": s0 - c0,
            "service_to_send_entry_us": s1 - s0,
            "post_send_entry_us": c1 - s1,
        }
        dominant = max(segments, key=lambda key: segments[key])
        if segments[dominant] / total < 0.8:
            dominant = "mixed"
        pairs.append(
            {
                "id": ident,
                "client_callback_us": total,
                **segments,
                "service_thread_cpu_us": (
                    e["Ssend_entry"]["thread_cpu_ns"] - e["Sparsed"]["thread_cpu_ns"]
                )
                / 1000,
                "send_call_wall_us": s2 - s1,
                "send_return_after_client": s2 > c1,
                "dominant_80pct": dominant,
                "slow_ge_10ms": total >= 10000,
            }
        )
    slow = [r for r in pairs if r["slow_ge_10ms"]]
    counts = Counter(r["dominant_80pct"] for r in slow)
    with (root / "matched-pairs.csv").open("w") as output:
        fields = list(pairs[0]) if pairs else ["id"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pairs)
    result = {
        "scope": "periodic sampled callback-boundary localization; not population quantiles, scheduler/network cause proof or qualification",
        "observed_unique_ids": len(events),
        "complete_valid_matched_ids": len(pairs),
        "invalid_or_partial_ids": dict(invalid),
        "client_summary_threads": len(summaries),
        "client_diagnostics": diagnostics,
        "server_dropped": server_dropped,
        "slow_sample_threshold_us": 10000,
        "slow_valid_matched_ids": len(slow),
        "slow_dominant_80pct_counts": dict(counts),
        "send_return_after_client_count": sum(r["send_return_after_client"] for r in pairs),
        "observed_windows": [
            {
                "index": w["index"],
                "pid": w["pid"],
                "checks_pass": w["checks_pass"],
                "metrics": w["raw"]["metrics"],
            }
            for w in windows
        ],
        "all_three_windows_valid": len(windows) == 3 and all(w["checks_pass"] for w in windows),
        "unexplained_scope": "Preparse includes client request generation/write, server wake/read/parse. Post-send-entry includes server assembly/send and client reactor/read/callback delivery. Thread CPU deficit does not distinguish blocked from runnable. Send return may legitimately follow client callback. Periodic samples and wrapper overhead may bias observations.",
        "qualified": False,
    }
    (root / "matched-analysis.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    print(json.dumps(analyze(p.parse_args().root), indent=2))
