# dexpot-native

Optional Rust request-head parsing for [dexpot](https://github.com/tugrulguner/dexpot).

The package accelerates request-line and header semantics while dexpot continues to own sockets,
deadlines, bodies, pipelining, target decoding, routing, handlers, scheduling, and supervision.
It is not a standalone server.

This package is alpha, is not yet published, and initially requires explicit opt-in. Build it
from this repository for development:

```bash
cd native
uv sync --group dev
VIRTUAL_ENV="$PWD/.venv" uvx maturin==1.15.0 develop --release
cd ..
DEXPOT_HTTP_PARSER=native dexpot serve main:app
```

The pure-Python parser remains dexpot's behavioral reference and fallback. Dexpot defaults to
`DEXPOT_HTTP_PARSER=auto`, which uses this package when installed and otherwise uses Python.
Installing the separate package is the opt-in decision. Broken native imports remain visible
rather than being silently hidden. Dexpot also
checks `PARSER_API_VERSION` before selecting the extension so incompatible parser contracts
fail at startup.

Standard CPython uses an `abi3` wheel covering 3.12 and newer GIL builds. Free-threaded CPython
3.14t uses a separate version-specific wheel, and importing it must keep
`sys._is_gil_enabled()` false.

See issue [#18](https://github.com/tugrulguner/dexpot/issues/18) for semantic parity,
benchmark methodology, and promotion gates. Docker Desktop results are directional rather than
bare-metal public performance claims.
