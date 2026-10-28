"""Prepare pinned source artifacts only; no native timing."""

import importlib.util
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HEAD = "0a81f541e564bf0fdfa850d0191ae0776b0ffb2f"


def main():
    spec = importlib.util.spec_from_file_location(
        "socket_diag", REPO / "scripts/socket_owner_diagnostic.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CANDIDATE = HEAD
    module.DRIVER.HEAD = HEAD
    module.DRIVER.RUN_REQUEST = module.request_spec()
    module.DRIVER.PREPARE_ONLY = True
    module.DRIVER.execute_qualification()


if __name__ == "__main__":
    main()
