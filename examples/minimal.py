"""Example: minimal dexpot app."""

from msgspec import Struct

from dexpot import Dex

dex = Dex()


class ItemOut(Struct):
    name: str
    price: float


@dex.get("/items/{item_id}", response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    """Fetch an item by id."""
    return ItemOut(name=f"item{item_id}", price=float(item_id))


if __name__ == "__main__":
    dex.serve(port=8000)
