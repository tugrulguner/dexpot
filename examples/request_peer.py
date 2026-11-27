"""Inspect a direct connection locally with a Dexpot development checkout."""

import os

from dexpot import Dex, Request

app = Dex()


@app.get("/peer")
def peer(request: Request):
    # This local diagnostic is not a user identifier or an authorization check.
    return {"peer": request.peer}


if __name__ == "__main__":
    app.serve("127.0.0.1", int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")))
