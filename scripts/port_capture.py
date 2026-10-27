"""Disposable-CI-only capture of the owned synthetic loopback server port."""

import contextlib
import json
import os
import re
import select
import subprocess
import time


@contextlib.contextmanager
def capture_port(port, root):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("privileged capture is restricted to disposable GitHub CI")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("expected owned ephemeral loopback server port")
    root.mkdir(exist_ok=False)
    pcap = root / "loopback.pcap"
    command = [
        "sudo",
        "-n",
        "/usr/sbin/tcpdump",
        "-n",
        "-i",
        "lo0",
        "-y",
        "NULL",
        "--immediate-mode",
        "-s",
        "0",
        "-B",
        "4096",
        "-w",
        str(pcap),
        "tcp port " + str(port) + " and host 127.0.0.1",
    ]
    state = {
        "port": port,
        "filter": command[-1],
        "scope": "owned synthetic loopback traffic on disposable CI only",
        "ready": False,
        "stop_returncode": None,
        "kernel_dropped": None,
    }
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )
    assert process.stderr is not None
    lines = []
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("capture exited before readiness")
            readable, _, _ = select.select(
                [process.stderr], [], [], min(1, max(0, deadline - time.monotonic()))
            )
            if readable:
                line = os.read(process.stderr.fileno(), 65536).decode("utf-8", "replace")
                lines.append(line)
                if "listening on lo0" in "".join(lines):
                    state["ready"] = True
                    state["ready_wall_ns"] = time.time_ns()
                    break
        if not state["ready"]:
            raise RuntimeError("capture readiness not observed within 15 seconds")
        yield state
    finally:
        if process.poll() is None:
            subprocess.run(
                ["sudo", "-n", "/bin/kill", "-INT", "-" + str(process.pid)], check=True, timeout=5
            )
        try:
            _, remaining = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["sudo", "-n", "/bin/kill", "-KILL", "-" + str(process.pid)], check=False, timeout=5
            )
            _, remaining = process.communicate(timeout=5)
            state["forced_stop"] = True
        state["stop_returncode"] = process.returncode
        lines.append((remaining or b"").decode("utf-8", "replace"))
        text = "".join(lines)
        for field, pattern in [
            ("captured", r"(\d+) packets? captured"),
            ("received_by_filter", r"(\d+) packets? received by filter"),
            ("kernel_dropped", r"(\d+) packets? dropped by kernel"),
        ]:
            match = re.search(pattern, text)
            state[field] = int(match.group(1)) if match else None
        (root / "tcpdump.log").write_text(text)
        if pcap.exists():
            subprocess.run(
                ["sudo", "-n", "chown", str(os.getuid()) + ":" + str(os.getgid()), str(pcap)],
                check=True,
                timeout=5,
            )
        (root / "capture.json").write_text(json.dumps(state, indent=2))
    if state["stop_returncode"] != 0 or state.get("forced_stop") or state["kernel_dropped"] != 0:
        raise RuntimeError("capture incomplete or missing zero-drop evidence: " + json.dumps(state))
