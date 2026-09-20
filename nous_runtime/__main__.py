"""Module fallback for the Nous command-line interface."""

from __future__ import annotations

from nous_runtime.cli.main import app


def main() -> None:
    """Run the authoritative Nous Typer application."""
    app()


if __name__ == "__main__":
    main()
