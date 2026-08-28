"""Install a built native wheel into clean interpreters and run its contract suite."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE_ROOT = Path(__file__).resolve().parents[1]


def interpreter(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--versions", nargs="+", required=True)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args()
    versions = [version for value in args.versions for version in value.split()]
    expected_version = tomllib.loads((NATIVE_ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]

    wheels = list(args.wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one wheel in {args.wheel_dir}, found {wheels}")
    wheel = wheels[0].resolve()

    for version in versions:
        with tempfile.TemporaryDirectory(prefix=f"dexpot-native-{version}-") as directory:
            venv = Path(directory) / "venv"
            subprocess.run(["uv", "venv", "--python", version, str(venv)], check=True)
            python = interpreter(venv)
            dependencies = [str(wheel), "pytest==9.1.1"]
            if args.project_root is None:
                dependencies.append("dexpot==0.2.0")
            else:
                dependencies.extend(["-e", f"{args.project_root.resolve()}[all,dev]"])
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), *dependencies],
                check=True,
            )
            command = [str(python)]
            free_threaded = version.endswith("t") or "+freethreaded" in version
            if free_threaded:
                command.extend(["-X", "gil=0"])
            subprocess.run(
                [*command, "-m", "pytest", str(ROOT / "native" / "tests"), "-q"],
                check=True,
            )
            verification = (
                "import sys, dexpot_native; "
                f"assert dexpot_native.__version__ == {expected_version!r}; "
                "assert dexpot_native.PARSER_API_VERSION == 1; "
                + ("assert not sys._is_gil_enabled(); " if free_threaded else "")
                + "print(dexpot_native.__version__)"
            )
            subprocess.run([*command, "-c", verification], check=True)
            if args.project_root is not None:
                env = os.environ.copy()
                env["DEXPOT_HTTP_PARSER"] = "native"
                env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
                integration_test = "test_e2e.py" if os.name == "nt" else "test_http_hardening.py"
                subprocess.run(
                    [
                        *command,
                        "-m",
                        "pytest",
                        str(args.project_root / "tests" / "test_parser_backend.py"),
                        str(args.project_root / "tests" / integration_test),
                        "-q",
                    ],
                    check=True,
                    env=env,
                )


if __name__ == "__main__":
    main()
