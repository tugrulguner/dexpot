"""Dynamic filters using Dexpot 0.10.0 or newer."""

import os

from dexpot import Dex, Request

app = Dex()
ITEMS = (
    {"name": "tea", "category": "drinks", "origin": "Japan"},
    {"name": "bread", "category": "food", "origin": "France"},
    {"name": "soap", "category": "household", "origin": "France"},
)


@app.get("/items")
def items(request: Request):
    try:
        pairs = request.query_pairs()
    except ValueError:
        return 422, {"detail": "invalid query encoding"}
    filters: dict[str, set[str]] = {}
    for key, value in pairs:
        if key not in ("category", "origin"):
            return 422, {"detail": "unknown filter"}
        filters.setdefault(key, set()).add(value)
    return {
        "items": [
            item["name"]
            for item in ITEMS
            if all(item[key] in allowed for key, allowed in filters.items())
        ]
    }


if __name__ == "__main__":
    app.serve(
        os.environ.get("DEXPOT_EXAMPLE_HOST", "127.0.0.1"),
        int(os.environ.get("DEXPOT_EXAMPLE_PORT", "8000")),
    )
