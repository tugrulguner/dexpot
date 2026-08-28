"""Optional native acceleration for dexpot."""

from importlib.metadata import version

from ._parser import parse_head

PARSER_API_VERSION = 1
__version__ = version("dexpot-native")

__all__ = ["PARSER_API_VERSION", "__version__", "parse_head"]
