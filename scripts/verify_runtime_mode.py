"""Prove actual server mode through unforced imports and real HTTP execution.

This is qualification tooling, not a thread-safety guarantee for application dependencies.
"""

import argparse
import importlib
import importlib.metadata
import json
import os
import shlex
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class ModeMismatch(RuntimeError):
    pass


def check_snapshot(info: dict[str, Any], expected: str, *, bound: bool) -> None:
    build, enabled = expected != "gil", expected != "ft"
    if info["free_threaded_build"] is not build or info["gil_enabled"] is not enabled:
        raise ModeMismatch(f"GIL state mismatch for {expected}: {info}")
    if info["launch_overrides"] != {"PYTHON_GIL": None, "gil": None}:
        raise ModeMismatch("unforced qualification rejects GIL launch overrides")
    if bound and (
        info["selected_gil_enabled"] is not enabled
        or info["execution_mode"] != ("pooled-gil" if enabled else "bounded-ft")
    ):
        raise ModeMismatch(f"selected execution mode differs from actual GIL state: {info}")


def snapshot(app: Any, phase: str) -> dict[str, Any]:
    info = app._runtime_info()
    info["phase"] = phase
    info["launch_overrides"] = {
        "PYTHON_GIL": os.environ.get("PYTHON_GIL"),
        "gil": sys._xoptions.get("gil"),
    }
    info["dependencies"] = {
        name: importlib.metadata.version(name) for name in ("dexpot", "msgspec")
    }
    native = sys.modules.get("dexpot_native")
    if native is not None:
        info["dependencies"]["dexpot-native"] = getattr(native, "__version__", "unknown")
    return info


def serve_child(port: int, import_record: Path, extension: Path | None, stage: str) -> None:
    import msgspec

    from dexpot import Dex, RawResponse

    if extension is not None:
        sys.path.insert(0, str(extension))
        if stage == "startup":
            importlib.import_module("_dexpot_gil_fallback")
    app = Dex()

    class Input(msgspec.Struct):
        value: int

    class Output(msgspec.Struct):
        value: int

    @app.get("/runtime")
    def runtime():
        return snapshot(app, "server_snapshot")

    @app.post("/typed", body=Input, response=Output)
    def typed(body: Input):
        return Output(body.value + 1)

    @app.get("/invalid", response=Output)
    def invalid():
        return {"value": "not-an-integer"}

    @app.get("/raw")
    def raw():
        return RawResponse(b"ready")

    @app.get("/lazy")
    def lazy():
        # Positive case exercises a genuinely deferred stdlib integration.
        importlib.import_module("fractions")
        if extension is not None and stage == "lazy":
            importlib.import_module("_dexpot_gil_fallback")
        return {"lazy": True}

    import_record.write_text(json.dumps(snapshot(app, "after_application_import")))
    app.serve(host="127.0.0.1", port=port)


def http(base: str, path: str, data: bytes | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(base + path, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as response:
        return response.code, response.read()


def run_case(
    expected: str, directory: Path, extension: Path | None = None, stage: str = "none"
) -> dict[str, Any]:
    report: dict[str, Any] = {"expected": expected, "stage": stage, "valid": False, "snapshots": []}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    record = directory / f"{expected}-{stage}-imports.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--expect",
        expected,
        "--serve-port",
        str(port),
        "--import-record",
        str(record),
        "--stage",
        stage,
    ]
    if extension is not None:
        command += ["--extension", str(extension)]
    env = dict(os.environ)
    env.update(DEXPOT_WORKERS="1", PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    report["command"] = command
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"server exited during startup: {process.returncode}")
            try:
                status, body = http(base, "/runtime")
                if status == 200:
                    break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("server startup timed out")
            time.sleep(0.025)
        imported = json.loads(record.read_text())
        report["snapshots"].append(imported)
        check_snapshot(imported, expected, bound=False)
        startup = json.loads(body)
        startup["phase"] = "after_startup"
        report["snapshots"].append(startup)
        check_snapshot(startup, expected, bound=True)
        assert http(base, "/typed", b'{"value":7}') == (200, b'{"value":8}')
        assert http(base, "/typed", b'{"value":"bad"}')[0] == 422
        assert http(base, "/invalid")[0] == 500
        assert http(base, "/raw") == (200, b"ready")
        after = json.loads(http(base, "/runtime")[1])
        after["phase"] = "after_routes"
        report["snapshots"].append(after)
        check_snapshot(after, expected, bound=True)
        assert http(base, "/lazy") == (200, b'{"lazy":true}')
        lazy = json.loads(http(base, "/runtime")[1])
        lazy["phase"] = "after_lazy_import"
        report["snapshots"].append(lazy)
        check_snapshot(lazy, expected, bound=True)
        # Windows venv redirectors may launch the actual Python server as a
        # child with a different PID. Anchor all HTTP evidence to that server's
        # private per-launch application-import record, not the launcher PID.
        report.update(launcher_pid=process.pid, server_pid=imported["pid"])
        if {row["pid"] for row in report["snapshots"]} != {imported["pid"]}:
            raise ModeMismatch("runtime evidence did not come from the actual serving process")
        report["valid"] = True
    except ModeMismatch as exc:
        report.update(error=str(exc), failure_kind="runtime_mode")
    except Exception as exc:
        report.update(error=repr(exc), failure_kind="execution")
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            report.update(valid=False, error="server did not stop", failure_kind="execution")
        report.update(
            server_stdout=stdout, server_stderr=stderr, server_returncode=process.returncode
        )
    return report


def build_unsupported_extension(directory: Path) -> Path:
    if os.name != "posix":
        raise RuntimeError("the automatic-fallback C fixture is compiled on POSIX CI")
    source = directory / "fallback.c"
    source.write_text("""#include <Python.h>
static struct PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_dexpot_gil_fallback", NULL, -1, NULL
};
PyMODINIT_FUNC PyInit__dexpot_gil_fallback(void) {
    return PyModule_Create(&definition);
}
""")
    output = directory / ("_dexpot_gil_fallback" + str(sysconfig.get_config_var("EXT_SUFFIX")))
    command = shlex.split(sysconfig.get_config_var("CC") or "cc")
    command += [
        "-shared",
        "-fPIC",
        "-I" + sysconfig.get_path("include"),
        str(source),
        "-o",
        str(output),
    ]
    if sys.platform == "darwin":
        command += ["-undefined", "dynamic_lookup"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"fallback fixture build failed: {result.stdout}\n{result.stderr}")
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", choices=("gil", "ft", "ft-gil"), required=True)
    parser.add_argument("--negative-extension", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--import-record", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--extension", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--stage", choices=("none", "startup", "lazy"), default="none", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if os.environ.get("PYTHON_GIL") is not None or "gil" in sys._xoptions:
        parser.error("unforced runtime qualification rejects a GIL launch override")
    if args.serve_port is not None:
        if args.import_record is None:
            parser.error("child server requires --import-record")
        serve_child(args.serve_port, args.import_record, args.extension, args.stage)
        return 0
    with tempfile.TemporaryDirectory(prefix="dexpot-runtime-mode-") as temporary:
        directory = Path(temporary)
        positive = run_case(args.expect, directory)
        report: dict[str, Any] = {"positive": positive, "automatic_fallback_detected": []}
        if args.negative_extension:
            if args.expect != "ft" or not sysconfig.get_config_var("Py_GIL_DISABLED"):
                parser.error("negative extension qualification requires an unforced FT interpreter")
            extension = build_unsupported_extension(directory)
            negative = [
                run_case("ft", directory, extension, stage) for stage in ("startup", "lazy")
            ]
            report["negative"] = negative
            report["automatic_fallback_detected"] = [
                row["stage"]
                for row in negative
                if not row["valid"] and row.get("failure_kind") == "runtime_mode"
            ]
            report["ft_gil_enabled"] = run_case("ft-gil", directory, extension, "startup")
        if args.output is not None:
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return (
            0
            if (
                positive["valid"]
                and (
                    not args.negative_extension
                    or (
                        report["automatic_fallback_detected"] == ["startup", "lazy"]
                        and report["ft_gil_enabled"]["valid"]
                    )
                )
            )
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
