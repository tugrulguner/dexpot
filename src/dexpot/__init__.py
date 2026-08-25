"""dexpot: synchronous APIs with adaptive GIL and free-threaded execution."""

from importlib.metadata import PackageNotFoundError, version

from .app import Dex
from .requests import Request

try:
    __version__ = version("dexpot")
except PackageNotFoundError:  # running from source without installation
    __version__ = "0.0.0.dev0"

__all__ = ["Dex", "Request", "__version__"]
