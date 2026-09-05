"""Registration namespaces must be explicit, never borrowed from caller frames."""

from __future__ import annotations

from typing import Any

import pytest

from dexpot import Dex, Request


def test_previous_factory_invocation_cannot_borrow_current_alias() -> None:
    def factory(alias: Any, previous: Any = None):
        Alias = alias

        def handler(request: Alias = None):  # type: ignore[valid-type]
            return request

        if previous is not None:
            app = Dex()
            # A default must not hide unresolved annotation provenance.
            with pytest.raises(TypeError, match="annotation_locals"):
                app.get("/")(previous)
            app.get("/", annotation_locals={"Alias": Request})(previous)
            endpoint = app._compile().endpoints[0]
            request = Request("GET", "/", {}, "", {})
            assert endpoint.invoke([], None, request) is request
        return handler

    first = factory(Request)
    factory(str, first)


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_explicit_namespace_is_snapshotted_and_not_cached_by_handler(method: str) -> None:
    def handler(request: Alias = None):  # type: ignore[name-defined]  # noqa: F821
        return request

    app = Dex()
    namespace: dict[str, Any] = {"Alias": Request}
    decorate = getattr(app, method)("/context", annotation_locals=namespace)
    namespace["Alias"] = str
    decorate(handler)
    getattr(app, method)("/ordinary", annotation_locals=namespace)(handler)
    context, ordinary = app._compile().endpoints
    request = Request("GET", "/context", {}, "", {})
    assert context.needs_request
    assert context.invoke([], None, request) is request
    assert not ordinary.needs_request
    assert ordinary.invoke([], None) is None
