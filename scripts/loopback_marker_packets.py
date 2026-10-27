"""Reconstruct diagnostic HTTP markers from an ordinary loopback PCAP capture."""

from __future__ import annotations

import re
import socket
import struct
from collections import defaultdict
from pathlib import Path


def _pcap_packets(path):
    data = Path(path).read_bytes()
    if data[:4] in (b"\x0a\x0d\x0d\x0a",):
        raise ValueError("pcapng is unsupported")
    magics = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    }
    if len(data) < 24 or data[:4] not in magics:
        raise ValueError("unsupported or malformed pcap")
    endian, resolution = magics[data[:4]]
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", data[:24])
    off, packets = 24, []
    while off < len(data):
        if off + 16 > len(data):
            raise ValueError("truncated pcap packet header")
        sec, frac, incl, orig = struct.unpack(endian + "IIII", data[off : off + 16])
        off += 16
        if off + incl > len(data):
            raise ValueError("truncated pcap packet data")
        packets.append(
            (
                sec * 1_000_000 + frac * 1_000_000 // resolution,
                linktype,
                data[off : off + incl],
                incl < orig,
            )
        )
        off += incl
    return packets


def _tcp_frame(link, frame):
    if link == 0:  # DLT_NULL, host-endian AF
        if len(frame) < 4:
            return
        family = struct.unpack("=I", frame[:4])[0]
        frame = frame[4:]
        if family not in (2, socket.AF_INET):
            return
    elif link == 108:  # DLT_LOOP, network-endian AF_INET
        if len(frame) < 4 or struct.unpack("!I", frame[:4])[0] != 2:
            return
        frame = frame[4:]
    elif link == 1:
        if len(frame) < 14:
            return
        typ = struct.unpack("!H", frame[12:14])[0]
        frame = frame[14:]
        while typ in (0x8100, 0x88A8, 0x9100):
            if len(frame) < 4:
                return
            typ = struct.unpack("!H", frame[2:4])[0]
            frame = frame[4:]
        if typ != 0x0800:
            return
    elif link not in (12, 101):
        raise ValueError(f"unsupported pcap link type {link}")
    if len(frame) < 20 or frame[0] >> 4 != 4:
        return
    ihl = (frame[0] & 15) * 4
    if ihl < 20 or len(frame) < ihl or frame[9] != 6:
        return
    total = struct.unpack("!H", frame[2:4])[0]
    if total < ihl + 20:
        return
    ip = frame[: min(total, len(frame))]
    frag = struct.unpack("!H", ip[6:8])[0]
    if frag & 0x3FFF:
        return  # fragmented IP cannot safely be reconstructed here
    tcp = ip[ihl:]
    if len(tcp) < 20:
        return
    sport, dport, seq, _ack = struct.unpack("!HHII", tcp[:12])
    doff = (tcp[12] >> 4) * 4
    if doff < 20 or len(tcp) < doff:
        return
    flags = tcp[13]
    return (ip[12:16], ip[16:20], sport, dport, seq, flags, tcp[doff : min(len(tcp), total - ihl)])


def parse_pcap(path, server_port):
    """Return IDs mapped to request/response tap observations and capture diagnostics."""
    if not 1 <= int(server_port) <= 65535:
        raise ValueError("invalid server_port")
    result = {
        "observations": {},
        "counts": {
            "capture_packets": 0,
            "stream_count": 0,
            "truncated_packets": 0,
            "conflicting_bytes": 0,
            "gapped_streams": 0,
            "duplicate_segments": 0,
            "ignored_packets": 0,
        },
        "unknowns": [],
    }
    flows = defaultdict(list)
    for ts, link, frame, trunc in _pcap_packets(path):
        result["counts"]["capture_packets"] += 1
        if trunc:
            result["counts"]["truncated_packets"] += 1
        try:
            parsed = _tcp_frame(link, frame)
        except ValueError as e:
            result["unknowns"].append(str(e))
            continue
        if not parsed:
            result["counts"]["ignored_packets"] += 1
            continue
        src, dst, sp, dp, seq, flags, payload = parsed
        if sp != server_port and dp != server_port:
            result["counts"]["ignored_packets"] += 1
            continue
        if src == b"\x7f\x00\x00\x01" and dst == b"\x7f\x00\x00\x01":
            pass
        else:
            result["counts"]["ignored_packets"] += 1
            continue
        key = (src, dst, sp, dp) if dp == server_port else (dst, src, dp, sp)
        direction = "request" if dp == server_port else "response"
        # flow includes client/server endpoints; direction stores each directional sequence space
        flows[(key, direction)].append((ts, seq, flags, payload))
    result["counts"]["stream_count"] = len(flows)
    for (flow, direction), segs in flows.items():
        # unwrap 32-bit seq relative to first segment; SYN consumes sequence number.
        segs.sort(key=lambda x: x[0])
        base = None
        cells = {}
        saw_syn = False
        for ts, seq, flags, payload in segs:
            if flags & 2:
                saw_syn = True
                if base is None:
                    base = (seq + 1) & 0xFFFFFFFF
            if base is None:
                base = seq
            delta = ((seq - base + 0x80000000) & 0xFFFFFFFF) - 0x80000000
            start = delta + (1 if flags & 2 else 0)
            repeated = False
            for j, b in enumerate(payload):
                pos = start + j
                if pos in cells:
                    old, _oldts = cells[pos]
                    if old == b:
                        repeated = True
                    else:
                        result["counts"]["conflicting_bytes"] += 1
                else:
                    cells[pos] = (b, ts)
            if repeated:
                result["counts"]["duplicate_segments"] += 1
        if not cells:
            continue
        lo, hi = min(cells), max(cells) + 1
        if (saw_syn and lo != 0) or any(i not in cells for i in range(lo, hi)):
            result["counts"]["gapped_streams"] += 1
            result["unknowns"].append(
                {
                    "flow": str(flow),
                    "direction": direction,
                    "reason": "sequence gap; stream excluded",
                }
            )
            continue
        buf = bytes(cells[i][0] for i in range(lo, hi))
        times = [cells[i][1] for i in range(lo, hi)]
        if result["counts"]["conflicting_bytes"]:
            # Mark only streams with an internal conflicting byte as unusable.
            conflicted = False
            for _ts, seq, flags, payload in segs:
                delta = ((seq - base + 0x80000000) & 0xFFFFFFFF) - 0x80000000
                start = delta + (1 if flags & 2 else 0)
                if any(
                    start + j in cells and cells[start + j][0] != b for j, b in enumerate(payload)
                ):
                    conflicted = True
            if conflicted:
                result["unknowns"].append(
                    {
                        "flow": str(flow),
                        "direction": direction,
                        "reason": "conflicting retransmission; stream excluded",
                    }
                )
                continue
        at = 0
        previous_message_end_us = None
        while at < len(buf):
            end = buf.find(b"\r\n\r\n", at)
            if end < 0:
                break
            headend = end + 4
            head = buf[at:end].split(b"\r\n")
            headers = {}
            try:
                for line in head[1:]:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()
                length = int(headers.get(b"content-length", b"0"))
            except (ValueError, TypeError):
                break
            msgend = headend + length
            if msgend > len(buf):
                break
            marker = headers.get(b"x-dexpot-diag-id")
            if marker:
                try:
                    ident = marker.decode("ascii")
                except UnicodeDecodeError:
                    ident = None
                if ident and re.fullmatch(r"[0-9]+(?:-[0-9]+){0,2}", ident):
                    obs = {
                        "start_us": min(times[at:headend]),
                        "headers_complete_us": max(times[at:headend]),
                        "end_us": max(times[at:msgend]) if length else max(times[at:headend]),
                        "previous_message_end_us": previous_message_end_us,
                        "flow": {
                            "client": socket.inet_ntop(socket.AF_INET, flow[0]),
                            "server": socket.inet_ntop(socket.AF_INET, flow[1]),
                            "client_port": flow[2],
                            "server_port": flow[3],
                            "direction": direction,
                        },
                    }
                    slot = result["observations"].setdefault(ident, {})
                    if direction in slot:
                        result["unknowns"].append(
                            {"id": ident, "reason": "duplicate HTTP marker observation"}
                        )
                    else:
                        slot[direction] = obs
            previous_message_end_us = max(times[at:msgend])
            at = msgend
    return result
