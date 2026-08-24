"""``dexpot`` CLI: run an app with ``dexpot main:app``."""

from __future__ import annotations

import importlib
import sys

try:
    import typer
except ImportError as exc:  # pragma: no cover
    print("The CLI requires the 'cli' extra: pip install 'dexpot[cli]'", file=sys.stderr)
    raise SystemExit(1) from exc

app = typer.Typer(help="Run dexpot applications.")


def _load(target: str):
    module_path, _, attr = target.partition(":")
    if not attr:
        print("Target must be 'module:attr', e.g. main:app", file=sys.stderr)
        raise SystemExit(1)
    module = importlib.import_module(module_path)
    return getattr(module, attr)


@app.command()
def serve(
    target: str = typer.Argument(..., help="App location, e.g. main:app"),
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Serve an application."""
    instance = _load(target)
    if not hasattr(instance, "serve"):
        print(f"{target} has no serve() — is it a dexpot Dex instance?", file=sys.stderr)
        raise SystemExit(1)
    instance.serve(host=host, port=port)


@app.command()
def version() -> None:
    """Print the installed dexpot version."""
    from . import __version__

    typer.echo(f"dexpot {__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()


def main() -> None:  # pragma: no cover
    app()
