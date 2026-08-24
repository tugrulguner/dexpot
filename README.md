# dexpot

A thread-per-request Python API framework built for free-threaded CPython.

No async/await. Plain functions on real threads. On Python 3.14t one process
uses every core; on classic GIL builds dexpot runs a bounded pool with honest
overload shedding.

```python
from msgspec import Struct
from dexpot import Dex

class ItemOut(Struct):
    name: str
    price: float

dex = Dex()

@dex.get("/items/{item_id}", response=ItemOut)
def get_item(item_id: int) -> ItemOut:
    """Fetch an item by id."""
    return ItemOut(name=f"item{item_id}", price=float(item_id))
```

Run it:

```
pip install "dexpot[cli]"
dexpot serve main:app --port 8000
```

## Why

Existing Python frameworks assume the GIL is immovable, so their concurrency
story is an event loop plus worker processes. Free-threaded CPython (3.14t)
makes that machinery unnecessary: threads scale across cores, shared state is
real, and blocking code is simply correct.

dexpot is built for that world — and still beats async frameworks on classic
GIL builds by removing per-request abstraction layers entirely.

- **Thread-per-request**: write plain functions; no coroutine machinery anywhere.
- **Typed bodies via msgspec**: fused C decode+validate; invalid input returns a precise 422.
- **Mode-adaptive scheduler**: unbounded threads on free-threaded builds; bounded pool + fast 503 shedding under GIL.
- **Single-write responses**: headers and JSON body are emitted together on the hot path.

## Status

Alpha. The serving core is benchmark-proven; framework features (DI,
middleware, streaming) are landing milestone by milestone. Not yet recommended
for production.

## License

MIT
