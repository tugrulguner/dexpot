"""Filter items by repeated category keys (Dexpot 0.10.0 or newer)."""

import os
from typing import Annotated

from dexpot import Dex, Query

ITEMS = (("tea", "drinks"), ("bread", "food"), ("soap", "household"))
app = Dex(openapi=True)


@app.get("/items")
def list_items(category: Annotated[list[str], Query("category")] = []):  # noqa: B006
    return {"items": [name for name, group in ITEMS if not category or group in category]}


if __name__ == "__main__":
    app.serve(
        host=os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
