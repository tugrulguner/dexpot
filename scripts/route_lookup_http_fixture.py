"""Private HTTP routing ablation hooks; no per-request timers or telemetry."""

import json
import os
import sys
import threading
from pathlib import Path

from route_lookup_probe import bind_lookup

STRATEGIES = {"original", "bound-shared", "local-proxy"}


def install(app, *, ft=None):
    requested = os.environ.get("ROUTE_LOOKUP_STRATEGY", "original")
    if requested not in STRATEGIES:
        raise ValueError("unsupported route lookup strategy")
    ft = not getattr(sys, "_is_gil_enabled", lambda: True)() if ft is None else ft
    cls = type(app)
    original_match, original_owner, original_serve = cls._match, cls._own_connection, app.serve
    local = threading.local()
    bindings, lock = [], threading.Lock()

    def owner(self, conn, buf, *, registered=False):
        if self is not app:
            return original_owner(self, conn, buf, registered=registered)
        if requested != "original":
            lookup, evidence = bind_lookup(
                self, requested, fallback=original_match.__get__(self, cls)
            )
            local.lookup = lookup
        else:
            literal = self._plan.router.literal
            evidence = {
                "same_route_values": True,
                "owns_mapping": False,
                "mapping_id": id(literal),
                "mapping_type": type(literal).__name__,
            }
        evidence = dict(evidence, thread_id=threading.get_ident(), strategy=requested, closed=False)
        with lock:
            bindings.append(evidence)
        try:
            return original_owner(self, conn, buf, registered=registered)
        finally:
            evidence["closed"] = True
            if requested != "original":
                del local.lookup

    def match(self, method, path):
        lookup = getattr(local, "lookup", None) if self is app else None
        return original_match(self, method, path) if lookup is None else lookup(method, path)

    if ft:
        cls._own_connection = owner
    if ft and requested != "original":
        cls._match = match

    def serve(*args, **kwargs):
        try:
            return original_serve(*args, **kwargs)
        finally:
            cls._match, cls._own_connection, app.serve = (
                original_match,
                original_owner,
                original_serve,
            )
            folder = Path.cwd() / "route-probes"
            folder.mkdir(exist_ok=True)
            with (folder / f"report-{os.getpid()}.json").open("x") as out:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "requested_strategy": requested,
                        "observed_strategy": (requested if bindings else "unobserved")
                        if ft
                        else "gil-bypass",
                        "bindings": bindings,
                        "candidate_qualified": False,
                    },
                    out,
                    indent=2,
                )

    app.serve = serve


def instrument_application(source):
    marker = 'if __name__ == "__main__":'
    assert source.count(marker) == 1
    source = source.replace(
        marker, "from route_lookup_http_fixture import install\ninstall(app)\n\n" + marker
    )
    marker = '"parser": PARSER_BACKEND,'
    assert source.count(marker) == 1
    return source.replace(
        marker,
        marker
        + '\n        "route_lookup_strategy": os.environ.get("ROUTE_LOOKUP_STRATEGY", "original"),',
    )
