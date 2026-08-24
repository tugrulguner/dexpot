"""dexpot: a thread-per-request Python API framework built for free-threaded CPython."""

from importlib.metadata import version

from .app import Dex
from .requests import Request

__version__ = version("dexpot")

__all__ = ["Dex", "Request", "__version__"]
