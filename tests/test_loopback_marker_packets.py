import socket
import struct

import pytest
from scripts.loopback_marker_packets import parse_pcap

PORT = 45678


def packet(payload, *, seq=1000, srcport=50000, dstport=PORT, ts=1, flags=0x18):
    tcp = (
        struct.pack("!HHII", srcport, dstport, seq & 0xFFFFFFFF, 0)
        + bytes([0x50, flags])
        + b"\x00\x00\x00\x00\x00\x00"
        + payload
    )
    ip = (
        bytes([0x45, 0])
        + struct.pack("!H", 20 + len(tcp))
        + b"\x00\x01\x40\x00"
        + bytes([64, 6])
        + b"\x00\x00"
        + socket.inet_aton("127.0.0.1")
        + socket.inet_aton("127.0.0.1")
    )
    return (
        struct.pack("<IIII", ts, 0, len(ip + tcp) + 14, len(ip + tcp) + 14)
        + b"\x00" * 12
        + b"\x08\x00"
        + ip
        + tcp
    )


def pcap(path, frames):
    path.write_bytes(
        b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 1) + b"".join(frames)
    )


def req(i="123"):
    return (
        b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Dexpot-Diag-Id: "
        + i.encode()
        + b"\r\nContent-Length: 0\r\n\r\n"
    )


def res(i="123"):
    body = b'{"ok":true}'
    return (
        b"HTTP/1.1 200 OK\r\nX-Dexpot-Diag-Id: "
        + i.encode()
        + b"\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )


def test_single_frame_request_response_and_id(tmp_path):
    f = tmp_path / "x.pcap"
    r = req()
    s = res()
    pcap(f, [packet(r, ts=1), packet(s, seq=3000, srcport=PORT, dstport=50000, ts=2)])
    out = parse_pcap(f, PORT)
    assert set(out["observations"]) == {"123"}
    assert set(out["observations"]["123"]) == {"request", "response"}
    assert out["observations"]["123"]["request"]["headers_complete_us"] == 1_000_000


def test_split_headers_body_and_out_of_order_retransmit(tmp_path):
    f = tmp_path / "x.pcap"
    data = req("234")
    cut = data.index(b"\r\n") + 2
    pcap(
        f,
        [
            packet(data[cut:], seq=1000 + cut, ts=3),
            packet(data[:cut], seq=1000, ts=2),
            packet(data[:cut], seq=1000, ts=4),
        ],
    )
    out = parse_pcap(f, PORT)
    assert "234" in out["observations"]
    assert out["counts"]["duplicate_segments"] > 0
    assert out["observations"]["234"]["request"]["headers_complete_us"] == 3_000_000


def test_gap_and_conflict_excluded(tmp_path):
    f = tmp_path / "gap.pcap"
    d = req()
    pcap(f, [packet(d[:10], seq=1000), packet(d[11:], seq=1011)])
    out = parse_pcap(f, PORT)
    assert not out["observations"] and out["counts"]["gapped_streams"] == 1
    f = tmp_path / "conflict.pcap"
    pcap(f, [packet(d, seq=1000), packet(b"X" + d[1:], seq=1000, ts=2)])
    out = parse_pcap(f, PORT)
    assert not out["observations"] and out["counts"]["conflicting_bytes"] > 0


def test_wrong_port_ignored(tmp_path):
    f = tmp_path / "x.pcap"
    pcap(f, [packet(req(), dstport=PORT + 1)])
    out = parse_pcap(f, PORT)
    assert not out["observations"] and out["counts"]["ignored_packets"] == 1


def test_pcapng_explicitly_rejected(tmp_path):
    f = tmp_path / "x.pcapng"
    f.write_bytes(b"\x0a\x0d\x0d\x0a")
    with pytest.raises(ValueError, match="pcapng"):
        parse_pcap(f, PORT)


def test_real_marker_shape_null_link_and_split_response_body(tmp_path):
    marker = "1709-1-64"
    request, response = req(marker), res(marker)
    split = response.index(b"\r\n\r\n") + 7
    records = [
        packet(request, ts=1),
        packet(response[:split], seq=3000, srcport=PORT, dstport=50000, ts=2),
        packet(response[split:], seq=3000 + split, srcport=PORT, dstport=50000, ts=3),
    ]
    null_records = []
    for record in records:
        sec, frac, _, _ = struct.unpack("<IIII", record[:16])
        frame = struct.pack("<I", 2) + record[30:]
        null_records.append(struct.pack("<IIII", sec, frac, len(frame), len(frame)) + frame)
    f = tmp_path / "null.pcap"
    f.write_bytes(
        b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 0) + b"".join(null_records)
    )
    out = parse_pcap(f, PORT)
    assert out["observations"][marker]["response"]["headers_complete_us"] == 2_000_000
    assert out["observations"][marker]["response"]["end_us"] == 3_000_000


def test_tcp_sequence_wrap(tmp_path):
    data = req("1709-2-128")
    cut = 40
    seq = 2**32 - 30
    f = tmp_path / "wrap.pcap"
    pcap(f, [packet(data[:cut], seq=seq, ts=1), packet(data[cut:], seq=seq + cut, ts=2)])
    assert "1709-2-128" in parse_pcap(f, PORT)["observations"]
