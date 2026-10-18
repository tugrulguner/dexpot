"""Comparable sync HTTP adapters: dexpot, FastAPI/Pydantic, Litestar/msgspec."""
from __future__ import annotations

import os
import sys
import time
from typing import Any

import msgspec

CONTRACT_MODE = os.environ.get("COMPARE_CONTRACT", "native").lower()
if CONTRACT_MODE not in {"native", "shared"}:
    raise ValueError(f"Unknown COMPARE_CONTRACT={CONTRACT_MODE!r}")
FLAVOR = os.environ.get("COMPARE_FRAMEWORK", "dexpot").lower()
SYNC_THREADS = int(os.environ.get("COMPARE_SYNC_THREADS", str((os.cpu_count() or 1) * 2 + 2)))


async def configure_sync_threads(_app: Any = None) -> None:
    import anyio
    anyio.to_thread.current_default_thread_limiter().total_tokens = SYNC_THREADS


class Dimensions(msgspec.Struct, frozen=True):
    width: int
    height: int


class Details(msgspec.Struct, frozen=True):
    category: str
    dimensions: Dimensions


class Item(msgspec.Struct, frozen=True):
    id: int
    name: str
    price: float


class NestedItem(msgspec.Struct, frozen=True):
    id: int
    name: str
    details: Details


def item_data(item_id: int) -> dict[str, Any]:
    return {"id": item_id, "name": f"item-{item_id}", "price": 9.99}


def nested_data(item_id: int) -> dict[str, Any]:
    return {"id": item_id, "name": f"item-{item_id}",
            "details": {"category": "demo", "dimensions": {"width": 2, "height": 3}}}


def do_work(kind: str, item_id: int = 7) -> Any:
    # Identical application-side operation and logical data on every adapter.
    if kind == "io":
        time.sleep(0.001)
    elif kind == "cpu":
        sum(i * i for i in range(500))
    is_nested = kind == "nested"
    data = nested_data(item_id) if is_nested else item_data(item_id)
    schema = NestedItem if is_nested else Item
    if CONTRACT_MODE == "shared":
        from compat import checked_projection
        return checked_projection(data, schema)
    if FLAVOR == "fastapi":
        return data
    if is_nested:
        return NestedItem(item_id, data["name"], Details("demo", Dimensions(2, 3)))
    return Item(item_id, data["name"], 9.99)


def large_nested_data() -> list[Any]:
    # Construct objects per HTTP request; deliberately do not cache/pre-encode JSON.
    count = int(os.environ.get("COMPARE_LARGE_ROWS", "64"))
    return [do_work("nested", i) for i in range(1, count + 1)]


def runtime_data() -> dict[str, Any]:
    gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else None
    if FLAVOR == "dexpot":
        info = app._runtime_info()
        worker_threads = None if info["selected_gil_enabled"] is False else info["pool_size"]
        connection_limit = info["connection_limit"] if info["selected_gil_enabled"] is False else None
        handler_thread_model = "dexpot-ft-thread-per-connection" if info["selected_gil_enabled"] is False else "dexpot-gil-worker-pool"
    else:
        handler_thread_model = "anyio-sync-worker-pool"
        worker_threads = SYNC_THREADS
        connection_limit = None
    dexpot_module = None
    if FLAVOR == "dexpot":
        import dexpot
        from dexpot._plans import EndpointPlan
        dexpot_module = dexpot.__file__
        marker = getattr(EndpointPlan('GET', '/', lambda: None, None, Item, '', []).resp_prepare, '__compiled_scalar__', False)
    else:
        marker = False
    return {"compiled_scalar": marker,"framework": FLAVOR, "contract": CONTRACT_MODE,
            "python": sys.version.split()[0], "gil_enabled": gil,
            "handler_thread_model": handler_thread_model,
            "configured_worker_threads": worker_threads,
            "connection_limit": connection_limit, "module": __file__,
            "dexpot_module": dexpot_module, "large_nested_rows": int(os.environ.get("COMPARE_LARGE_ROWS", "64"))}


def audit_payload(case: str) -> dict[str, Any]:
    payload: dict[str, Any] = item_data(7)
    if case == "extra":
        payload["undeclared"] = "must-not-appear"
    elif case == "private":
        payload["private_token"] = "must-not-appear"
    elif case == "wrong_type":
        payload["id"] = "7"
    elif case == "missing":
        del payload["price"]
    elif case == "nonfinite":
        payload["price"] = float("nan")
    elif case == "request":
        from dexpot import Request
        payload["private_context"] = Request("GET", "/audit/request", {}, "", {})
    else:
        raise ValueError(f"unknown contract audit case {case!r}")
    return payload


if FLAVOR == "fastapi":
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from pydantic import BaseModel, ConfigDict

    @asynccontextmanager
    async def lifespan(_app: Any):
        await configure_sync_threads()
        yield

    class ItemOut(BaseModel):
        model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)
        id: int
        name: str
        price: float

    class DimensionsOut(BaseModel):
        model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)
        width: int
        height: int

    class DetailsOut(BaseModel):
        model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)
        category: str
        dimensions: DimensionsOut

    class NestedOut(BaseModel):
        model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)
        id: int
        name: str
        details: DetailsOut


    app = FastAPI(lifespan=lifespan)

    @app.get("/items/{item_id}", response_model=ItemOut if CONTRACT_MODE == "native" else None)
    def get_item(item_id: int) -> Any:
        return do_work("item", item_id)

    @app.get("/io", response_model=ItemOut if CONTRACT_MODE == "native" else None)
    def io_work() -> Any:
        return do_work("io")

    @app.get("/cpu", response_model=ItemOut if CONTRACT_MODE == "native" else None)
    def cpu_work() -> Any:
        return do_work("cpu")

    @app.get("/nested/{item_id}", response_model=NestedOut if CONTRACT_MODE == "native" else None)
    def nested_item(item_id: int) -> Any:
        return do_work("nested", item_id)

    @app.get("/large-nested")
    def large_nested() -> Any:
        return large_nested_data()

    @app.get("/runtime")
    def runtime() -> dict[str, Any]:
        return runtime_data()

    if os.environ.get("COMPARE_AUDIT") == "1":
        @app.get("/audit/{case}", response_model=ItemOut if CONTRACT_MODE == "native" else None)
        def audit_response(case: str) -> Any:
            value = audit_payload(case)
            if CONTRACT_MODE == "shared":
                from compat import checked_projection
                return checked_projection(value, Item)
            return value

elif FLAVOR == "litestar":
    from litestar import Litestar, get

    LitestarItemOutput = Item if CONTRACT_MODE == "native" else dict[str, Any]
    LitestarNestedOutput = NestedItem if CONTRACT_MODE == "native" else dict[str, Any]

    @get("/items/{item_id:int}", sync_to_thread=True)
    def get_item(item_id: int) -> LitestarItemOutput:
        return do_work("item", item_id)

    @get("/io", sync_to_thread=True)
    def io_work() -> LitestarItemOutput:
        return do_work("io")

    @get("/cpu", sync_to_thread=True)
    def cpu_work() -> LitestarItemOutput:
        return do_work("cpu")

    @get("/nested/{item_id:int}", sync_to_thread=True)
    def nested_item(item_id: int) -> LitestarNestedOutput:
        return do_work("nested", item_id)

    @get("/large-nested", sync_to_thread=True)
    def large_nested() -> list[NestedItem]:
        return large_nested_data()

    @get("/runtime", sync_to_thread=True)
    def runtime() -> dict[str, Any]:
        return runtime_data()

    handlers = [get_item, io_work, cpu_work, nested_item, large_nested, runtime]
    if os.environ.get("COMPARE_AUDIT") == "1":
        @get("/audit/{case:str}", sync_to_thread=True)
        def audit_response(case: str) -> Item:
            value = audit_payload(case)
            if CONTRACT_MODE == "shared":
                from compat import checked_projection
                return checked_projection(value, Item)
            return value
        handlers.append(audit_response)
    app = Litestar(route_handlers=handlers, on_startup=[configure_sync_threads])

elif FLAVOR == "dexpot":
    # Candidate is imported from its frozen installed wheel, never via PYTHONPATH.
    # Baseline remains a deliberate source-path selection in runner.py.
    site = os.environ.get("COMPARE_DEXPOT_SITE")
    if site:
        sys.path.insert(0, site)
    os.environ.setdefault("DEXPOT_POOL", str(SYNC_THREADS))
    os.environ.setdefault("DEXPOT_MAX_CONNECTIONS", os.environ.get("COMPARE_MAX_CONNECTIONS", "1024"))
    from dexpot import Dex
    from runtime_identity import emit_runtime_event

    import multiprocessing
    import threading

    class AuditedDex(Dex):
        """Fixture-only lifecycle records, never a per-request GIL query."""

        def __init__(self):
            super().__init__()
            self._identity_write_lock = (
                multiprocessing.get_context("fork").Lock()
                if os.name == "posix" else threading.Lock()
            )

        def _report_startup(self) -> None:
            if getattr(self, "_identity_startup_pid", None) != os.getpid():
                self._identity_startup_pid = os.getpid()
                emit_runtime_event(self, "startup")

        def _start_gil_workers(self, listener):
            super()._start_gil_workers(listener)
            self._report_startup()

        def _handle_admission(self, conn, buf):
            # FT has no GIL worker-pool startup hook. This flag is checked once
            # per connection admission, not during request dispatch.
            self._report_startup()
            return super()._handle_admission(conn, buf)

        def _begin_drain(self, timeout):
            try:
                return super()._begin_drain(timeout)
            finally:
                if getattr(self, "_identity_final_pid", None) != os.getpid():
                    self._identity_final_pid = os.getpid()
                    emit_runtime_event(self, "after_workload")

    app = AuditedDex()

    @app.get("/items/{item_id}", response=Item if CONTRACT_MODE == "native" else None)
    def get_item(item_id: int) -> Item:
        return do_work("item", item_id)

    @app.get("/io", response=Item if CONTRACT_MODE == "native" else None)
    def io_work() -> Item:
        return do_work("io")

    @app.get("/cpu", response=Item if CONTRACT_MODE == "native" else None)
    def cpu_work() -> Item:
        return do_work("cpu")

    @app.get("/nested/{item_id}", response=NestedItem if CONTRACT_MODE == "native" else None)
    def nested_item(item_id: int) -> NestedItem:
        return do_work("nested", item_id)

    @app.get("/large-nested", response=list[NestedItem])
    def large_nested() -> list[NestedItem]:
        return large_nested_data()

    @app.get("/runtime")
    def runtime() -> dict[str, Any]:
        return runtime_data()

    if os.environ.get("COMPARE_AUDIT") == "1":
        @app.get("/audit/{case}", response=Item if CONTRACT_MODE == "native" else None)
        def audit_response(case: str) -> Any:
            value = audit_payload(case)
            if CONTRACT_MODE == "shared":
                from compat import checked_projection
                return checked_projection(value, Item)
            return value

else:
    raise ValueError(f"Unknown COMPARE_FRAMEWORK={FLAVOR!r}")


def serve() -> None:
    port = int(os.environ.get("COMPARE_PORT", "18881"))
    server = os.environ.get("COMPARE_SERVER", "granian").lower()
    workers = int(os.environ.get("COMPARE_WORKERS", "1"))
    blocking_threads = os.environ.get("COMPARE_BLOCKING_THREADS")
    if FLAVOR == "dexpot":
        os.environ["DEXPOT_WORKERS"] = str(workers)
        app.serve(host="127.0.0.1", port=port)
    elif server == "granian":
        from granian import Granian
        options = {"workers": workers}
        if blocking_threads:
            options["blocking_threads"] = int(blocking_threads)
        Granian("app:app", address="127.0.0.1", port=port, interface="asgi", **options).serve()
    elif server == "uvicorn":
        import uvicorn
        uvicorn.run("app:app", host="127.0.0.1", port=port, workers=workers, log_level="warning")
    else:
        raise ValueError(f"Unknown COMPARE_SERVER={server!r}")


if __name__ == "__main__":
    serve()
