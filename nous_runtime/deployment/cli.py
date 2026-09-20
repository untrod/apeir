"""CLI for the product installation layout service."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.deployment.product_installer import (
    InstallMode,
    ProductInstaller,
)


install_app = typer.Typer(
    help="Plan and apply a Nous product installation."
)


@install_app.command("plan")
def plan_install(
    path: Path = typer.Option(Path("Nous"), "--path"),
    mode: InstallMode = typer.Option(
        InstallMode.RECOMMENDED, "--mode"
    ),
) -> None:
    """Inspect components and hardware recommendations without writing."""
    typer.echo(
        json.dumps(
            ProductInstaller(path).plan(mode).to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )


@install_app.command("apply")
def apply_install(
    path: Path = typer.Option(Path("Nous"), "--path"),
    mode: InstallMode = typer.Option(
        InstallMode.RECOMMENDED, "--mode"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Create the recoverable product layout selected by the installer."""
    if not dry_run and not yes:
        if not typer.confirm(f"Install Nous into {path.resolve()}?"):
            typer.echo("Cancelled.")
            return
    plan = ProductInstaller(path).apply(mode, dry_run=dry_run)
    typer.echo(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))


@install_app.command("wizard")
def setup_wizard(
    path: str = typer.Option("", "--path", help="Install path"),
) -> None:
    """Run the interactive product setup wizard."""
    from nous_runtime.deployment.setup_wizard import (
        ConsoleSetupWizard,
        save_setup_config,
    )
    from pathlib import Path as P

    wizard = ConsoleSetupWizard(path if path else None)
    config = wizard.run()
    save_setup_config(
        config,
        P(config.install_path) / "setup_config.json",
    )
    typer.echo(f"\nConfiguration saved to {config.install_path}")


def register_install_commands(app: typer.Typer) -> None:
    app.add_typer(install_app, name="install")


__all__ = ["install_app", "register_install_commands", "setup_wizard"]
