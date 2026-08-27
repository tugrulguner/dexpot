"""dexpot CLI: serve applications and install framework guidance."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

try:
    import typer
except ImportError as exc:  # pragma: no cover
    print("The CLI requires the 'cli' extra: pip install 'dexpot[cli]'", file=sys.stderr)
    raise SystemExit(1) from exc

from dexpot.commands.add_skills import add_skills


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"dexpot {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="dexpot",
    help="A synchronous Python API framework built for free-threaded CPython.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Serve plain Python handlers through dexpot's adaptive threaded runtime."""


add_app = typer.Typer(help="Add dexpot support to a project.", no_args_is_help=True)
app.add_typer(add_app, name="add")
add_app.command("skills")(add_skills)


def _load(target: str) -> Any:
    module_path, separator, attr = target.partition(":")
    if not separator or not module_path or not attr:
        typer.echo("Error: target must be 'module:attribute', e.g. main:app", err=True)
        raise typer.Exit(1)
    sys.path.insert(0, str(Path.cwd()))
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        typer.echo(f"Error importing {module_path}: {exc}", err=True)
        raise typer.Exit(1) from None
    try:
        return getattr(module, attr)
    except AttributeError:
        typer.echo(f"Error: {module_path} has no attribute {attr!r}", err=True)
        raise typer.Exit(1) from None


@app.command("serve")
def serve_command(
    target: str = typer.Argument(..., help="Application location, e.g. main:app."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to."),
) -> None:
    """Serve a Dex application as an HTTP API."""
    instance = _load(target)
    if not hasattr(instance, "serve"):
        typer.echo(
            f"Error: {target} has no serve() method; expected a dexpot Dex instance",
            err=True,
        )
        raise typer.Exit(1)
    instance.serve(host=host, port=port)


@app.command()
def version() -> None:
    """Print the installed dexpot version."""
    from . import __version__

    typer.echo(f"dexpot {__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()
