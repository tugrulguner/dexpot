"""Worker app module for multiprocess supervisor testing (spawned via subprocess)."""

from __future__ import annotations

import sys

from dexpot import Dex

app = Dex()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


if __name__ == "__main__":
    port = int(sys.argv[1])
    app.serve(host="127.0.0.1", port=port)
