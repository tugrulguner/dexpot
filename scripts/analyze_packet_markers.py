"""Join packet-tap observations to diagnostic callbacks; no syscall/lock causality claim."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from loopback_marker_packets import parse_pcap


def analyze(root, capture_root=None):
    capture_root = capture_root or root / "capture"
    capture = json.loads((capture_root / "capture.json").read_text())
    packet = parse_pcap(capture_root / "loopback.pcap", capture["port"])
    (root / "packet-observations.json").write_text(json.dumps(packet, indent=2))
    markers = defaultdict(lambda: defaultdict(list))
    for f in (root / "markers").glob("*.jsonl"):
        for line in f.read_text().splitlines():
            row = json.loads(line)
            if "id" in row:
                markers[row["id"]][row["event"]].append(row)
    expected = [
        "Crequest_prepared",
        "Sread_entry",
        "Sparsed",
        "Ssend_entry",
        "Ssend_return",
        "Cresponse_callback_entry",
    ]
    invalid = Counter()
    pairs = []
    for ident, states in markers.items():
        if any(len(states.get(name, [])) != 1 for name in expected):
            invalid["missing_or_duplicate_marker"] += 1
            continue
        e = {name: states[name][0] for name in expected}
        tap = packet["observations"].get(ident, {})
        if set(tap) != {"request", "response"}:
            invalid["missing_packet_pair"] += 1
            continue
        request, response = tap["request"], tap["response"]
        if request["flow"]["client_port"] != response["flow"]["client_port"]:
            invalid["packet_connection_mismatch"] += 1
            continue
        c0 = e["Crequest_prepared"]["wall_us"]
        c1 = e["Cresponse_callback_entry"]["wall_us"]
        r0 = e["Sread_entry"]["wall_us"]
        s0 = e["Sparsed"]["wall_us"]
        s1 = e["Ssend_entry"]["wall_us"]
        p1 = request["end_us"]
        p2 = response["end_us"]
        points = [c0, p1, s0, s1, p2, c1]
        if (
            any(type(p) is not int for p in points)
            or any(a > b + 2 for a, b in pairwise(points))
            or r0 > s0
        ):
            invalid["clock_or_boundary_order"] += 1
            continue
        total = c1 - c0
        if total <= 0:
            invalid["nonpositive_interval"] += 1
            continue
        parts = {
            "client_pre_request_tap_us": p1 - c0,
            "server_request_tap_to_parsed_us": s0 - p1,
            "service_to_send_entry_us": s1 - s0,
            "send_entry_to_response_tap_us": p2 - s1,
            "client_response_tap_to_callback_us": c1 - p2,
        }
        dominant = max(parts, key=lambda key, parts=parts: parts[key])
        if parts[dominant] / total < 0.8:
            dominant = "mixed"
        previous = states.get("Sprevious_send_return", [])
        previous_return = previous[0]["wall_us"] if len(previous) == 1 else None
        previous_tap = response.get("previous_message_end_us")
        prior_gap = (
            previous_return - previous_tap
            if previous_return is not None and previous_tap is not None
            else None
        )
        pairs.append(
            {
                "id": ident,
                "total_callback_us": total,
                **parts,
                "read_entry_minus_request_tap_us": r0 - p1,
                "read_wall_us": s0 - r0,
                "read_thread_cpu_us": (
                    e["Sparsed"]["thread_cpu_ns"] - e["Sread_entry"]["thread_cpu_ns"]
                )
                / 1000,
                "previous_response_tap_to_send_return_us": prior_gap,
                "previous_send_return_minus_request_tap_us": previous_return - p1
                if previous_return is not None
                else None,
                "dominant_80pct": dominant,
                "slow_ge_10ms": total >= 10000,
            }
        )
    slow = [p for p in pairs if p["slow_ge_10ms"]]
    with (root / "packet-pairs.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(pairs[0]) if pairs else ["id"])
        writer.writeheader()
        writer.writerows(pairs)
    result = {
        "scope": "capture-tap boundary localization of periodic samples; not syscall timestamps, GIL/host cause proof or qualification",
        "capture": capture,
        "packet_counts": packet["counts"],
        "packet_unknowns": packet["unknowns"],
        "observed_marker_ids": len(markers),
        "complete_packet_and_marker_joins": len(pairs),
        "invalid_or_partial_ids": dict(invalid),
        "slow_threshold_us": 10000,
        "slow_count": len(slow),
        "slow_dominant_80pct_counts": dict(Counter(p["dominant_80pct"] for p in slow)),
        "slow_samples": slow,
        "capture_zero_drop_verified": capture.get("kernel_dropped") == 0
        and capture.get("stop_returncode") == 0,
        "qualified": False,
        "limits": "Packet timestamps are observations at the loopback tap, not native write/read syscalls. Pre-request-tap may include client scheduling, formatting, write or socket backpressure. Post-request-tap includes kernel receive, server read/parse and wake/scheduling. Read thread CPU covers the entire API call, possibly beginning before packet arrival; deficit is not a blocked-versus-runnable classification.",
    }
    (root / "packet-analysis.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    print(json.dumps(analyze(parser.parse_args().root), indent=2))
