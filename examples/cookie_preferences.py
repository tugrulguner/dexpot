"""Read a display preference with Dexpot 0.11.0 or newer."""

import os

from dexpot import Dex, Request

app = Dex()


@app.get("/preferences")
def preferences(request: Request):
    try:
        pairs = request.cookie_pairs()
    except ValueError:
        return 422, {"detail": "invalid cookie header"}

    themes = [value for name, value in pairs if name == "theme"]
    if not themes:
        return {"theme": "light"}
    if len(themes) != 1 or themes[0] not in ("light", "dark"):
        return 422, {"detail": "invalid theme preference"}
    return {"theme": themes[0]}


if __name__ == "__main__":
    app.serve(
        os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
