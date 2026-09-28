---
title: Quick start
description: Install Dexpot, define a typed synchronous Python API, serve it, and call its HTTP routes.
---

import { Aside, Steps } from '@astrojs/starlight/components';

<Steps>

1. **Install the framework and CLI**

   ```bash
   pip install "dexpot[cli]"
   ```

2. **Define an application**

   Save this as `main.py`:

   ```python
   import msgspec

   from dexpot import Dex


   class ItemIn(msgspec.Struct):
       name: str
       price: float


   class ItemOut(msgspec.Struct):
       id: int
       name: str
       price: float


   app = Dex()


   @app.get("/items/{item_id}", response=ItemOut)
   def get_item(item_id: int) -> ItemOut:
       return ItemOut(id=item_id, name=f"item-{item_id}", price=9.99)


   @app.post("/items", body=ItemIn, response=ItemOut)
   def create_item(item: ItemIn) -> tuple[int, ItemOut]:
       return 201, ItemOut(id=1, name=item.name, price=item.price)
   ```

3. **Serve it**

   ```bash
   dexpot serve main:app --host 127.0.0.1 --port 8000
   ```

4. **Call the real HTTP surface**

   ```bash
   curl -s http://127.0.0.1:8000/items/7
   curl -s -X POST http://127.0.0.1:8000/items \
     -H 'Content-Type: application/json' \
     -d '{"name":"keyboard","price":79.0}'
   ```

   The responses are JSON:

   ```json
   {"id":7,"name":"item-7","price":9.99}
   ```

   ```json
   {"id":1,"name":"keyboard","price":79.0}
   ```

</Steps>

You can also run the file directly:

```python
if __name__ == "__main__":
    app.serve(host="127.0.0.1", port=8000)
```

<Aside type="note">
The path capture is converted to `int` from its annotation. The POST body is decoded and validated directly into `ItemIn`; malformed JSON or validation failures return 422.
</Aside>

Continue with the [route contract](/route-contract/) or see the [runnable examples](/examples/).
