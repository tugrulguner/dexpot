"""Request object handed to handlers."""

from __future__ import annotations

from typing import Any


class Request:
    """One parsed HTTP request. Typed bodies are exposed via ``body``."""

    __slots__ = ("_body", "headers", "method", "params", "path", "query")

    def __init__(
        self,
        method: str,
        path: str,
        params: dict[str, str],
        query: str,
        headers: dict[str, str],
    ) -> None:
        self.method = method
        self.path = path
        self.params = params
        self.query = query
        self.headers = headers
        self._body: Any = None

    @property
    def body(self) -> Any:
        """The validated body object (set by the dispatcher before the handler runs)."""
        return self._body
