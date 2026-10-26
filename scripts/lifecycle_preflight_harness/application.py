"""Synthetic checked-output workload. Not a database/production-service benchmark."""

import argparse
import importlib.metadata
import os
import sys
import sysconfig
import time

from msgspec import Struct

import dexpot
from dexpot import Dex
from dexpot._http import PARSER_BACKEND


class Item(Struct):
    id: int
    name: str
    price: float


class Group(Struct):
    items: list[Item]
    title: str


app = Dex()


@app.get("/flat", response=Item)
def flat() -> Item:
    return Item(7, "item-7", 9.99)


@app.get("/nested", response=Group)
def nested() -> Group:
    return Group([Item(i, f"item-{i}", 9.99) for i in range(16)], "group")


@app.get("/cpu", response=Item)
def cpu() -> Item:
    # Deliberate pure-Python application work, identical in both interpreter modes.
    sum(i * i for i in range(400))
    return flat()


@app.get("/io", response=Item)
def io() -> Item:
    # Simulated blocking wait; this is not real database/outbound-I/O evidence.
    time.sleep(0.001)
    return flat()


@app.get("/runtime")
def runtime() -> dict:
    affinity = getattr(os, "sched_getaffinity", None)
    return {
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "ft_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "selected_ft": app._serving_gil_free,
        "module": dexpot.__file__,
        "version": importlib.metadata.version("dexpot"),
        "python": sys.version,
        "pid": os.getpid(),
        "cpu_affinity": sorted(affinity(0)) if affinity is not None else None,
        "parser": PARSER_BACKEND,
    }


if os.environ.get("DEXPOT_PREFLIGHT_BARRIER") == "1":

    @app.get("/_preflight")
    def preflight_state() -> dict:
        # This observer exists only in the separate preflight process, never
        # the timed workload. Its keep-alive connection is one held position.
        with app._cond:
            active = len(app._active_connections)
            queued = len(app._work)
        module = sys.modules[type(app).__module__]
        slots = getattr(module, "_FT_CONNECTION_SLOTS", None)
        available = None
        live = None
        if slots is not None:
            with slots._cond:
                available = slots._value
            # Dead owners intentionally retain permits until the next native
            # admission reaps/joins them. Observe live owners, never reap here.
            with module._FT_OWNERS_LOCK:
                live = sum(
                    thread.is_alive()
                    for thread, owner in module._FT_OWNERS.items()
                    if owner[0] is app
                )
        return {
            "active": active,
            "queued": queued,
            "available_ft": available,
            "live_ft_owners": live,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    app.serve("127.0.0.1", args.port)
