"""Simplified management commands for model runtime and distribution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from nous_runtime.model_distribution import (
    Ed25519CatalogVerifier,
    ModelCatalog,
    ModelDistributionManager,
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_runtime import (
    HardwareBudget,
    ModelCapabilityResolver,
    ModelLifecycleState,
    ModelRuntimeRegistry,
    detect_hardware_budget,
)


models_app = typer.Typer(
    help="Manage unified model runtime and distribution."
)


def _workspace_root() -> Path:
    return Path(os.environ.get("NOUS_WORKSPACE_ROOT") or ".nous")


def _registry_path() -> Path:
    configured = os.environ.get("NOUS_MODEL_REGISTRY")
    return (
        Path(configured)
        if configured
        else _workspace_root() / "models" / "registry.json"
    )


def _registry() -> ModelRuntimeRegistry:
    return ModelRuntimeRegistry(_registry_path())


@models_app.command("list")
def list_models(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List installed and registered model records."""
    records = _registry().list(include_removed=True)
    if as_json:
        typer.echo(
            json.dumps(
                [item.to_dict() for item in records],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not records:
        typer.echo("No unified models registered.")
        return
    for item in records:
        typer.echo(
            f"{item.descriptor.model_id:30s} "
            f"{item.state.value:12s} "
            f"{item.descriptor.endpoint_type.value:16s} "
            f"{item.location or '-'}"
        )


@models_app.command("show")
def show_model(
    model_id: str = typer.Argument(..., help="Unified model ID"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show one unified model record."""
    record = _registry().get(model_id)
    if record is None:
        typer.echo(f"Model '{model_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(
            json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(f"Model:      {record.descriptor.model_id}")
    typer.echo(f"Display:    {record.descriptor.display_name}")
    typer.echo(f"State:      {record.state.value}")
    typer.echo(f"Endpoint:   {record.descriptor.endpoint_type.value}")
    typer.echo(f"Provider:   {record.descriptor.provider_id}")
    typer.echo(f"Location:   {record.location or '-'}")
    typer.echo(
        "Capabilities: "
        + (", ".join(sorted(record.descriptor.capabilities)) or "none")
    )
    typer.echo(
        "Modalities: "
        + ", ".join(
            sorted(
                item.value for item in record.descriptor.modalities
            )
        )
    )


@models_app.command("import")
def import_model(
    source: Path = typer.Argument(..., exists=True, readable=True),
    model_id: str = typer.Option("", "--model-id"),
    display_name: str = typer.Option("", "--name"),
    copy_model: bool = typer.Option(
        False,
        "--copy",
        help="Copy into Nous instead of referencing the source.",
    ),
    capability: list[str] = typer.Option(
        ["reasoning"],
        "--capability",
        help="Declared capability; repeat for multiple values.",
    ),
) -> None:
    """Import GGUF, SafeTensors, ONNX, Ollama, or model directories."""
    registry = _registry()
    destination = _workspace_root() / "models" / "imported"
    imported, record = ModelDistributionManager(registry).import_local(
        source,
        model_id=model_id,
        display_name=display_name,
        reference=not copy_model,
        destination_root=destination if copy_model else None,
        capabilities=tuple(capability),
    )
    typer.echo(f"Imported: {record.descriptor.model_id}")
    typer.echo(f"Format:   {imported.format}")
    typer.echo(f"Location: {imported.location}")
    typer.echo("State:    registered (enable explicitly before use)")


@models_app.command("enable")
def enable_model(model_id: str = typer.Argument(...)) -> None:
    """Enable a registered model without loading it."""
    record = _registry().enable(model_id)
    typer.echo(f"{record.descriptor.model_id}: {record.state.value}")


@models_app.command("disable")
def disable_model(model_id: str = typer.Argument(...)) -> None:
    """Disable a model and its instances."""
    record = _registry().disable(model_id)
    typer.echo(f"{record.descriptor.model_id}: {record.state.value}")


def _load_catalog(
    path: Path,
    public_key: str,
    allow_unsigned: bool,
) -> ModelCatalog:
    verifier = Ed25519CatalogVerifier(public_key) if public_key else None
    return ModelCatalog.load(
        path,
        verifier=verifier,
        require_signature=not allow_unsigned,
    )


@models_app.command("resolve")
def resolve_models(
    catalog_path: Path = typer.Argument(..., exists=True, readable=True),
    capability: list[str] = typer.Option(
        [],
        "--capability",
        help="Required capability; repeat for multiple values.",
    ),
    modality: list[str] = typer.Option(
        ["text"],
        "--modality",
        help="Required modality; repeat for multiple values.",
    ),
    disk_mb: int = typer.Option(0, "--disk-mb"),
    vram_mb: int = typer.Option(0, "--vram-mb"),
    public_key: str = typer.Option(
        "",
        "--catalog-public-key",
        envvar="NOUS_MODEL_CATALOG_PUBLIC_KEY",
    ),
    allow_unsigned: bool = typer.Option(
        False,
        "--allow-unsigned",
        help="Only for trusted local development catalogs.",
    ),
) -> None:
    """Resolve the smallest approved package set from a catalog."""
    catalog = _load_catalog(
        catalog_path,
        public_key,
        allow_unsigned,
    )
    packages = [
        package
        for model in catalog.models
        for package in model.packages
    ]
    hardware = (
        HardwareBudget(disk_mb=disk_mb, vram_mb=vram_mb)
        if disk_mb or vram_mb
        else detect_hardware_budget(catalog_path.parent)
    )
    resolution = ModelCapabilityResolver(packages).resolve(
        capabilities=capability,
        modalities=modality,
        hardware=hardware,
    )
    typer.echo(
        json.dumps(
            {
                "complete": resolution.complete,
                "selected_packages": [
                    item.package_id
                    for item in resolution.selected_packages
                ],
                "covered_capabilities": sorted(
                    resolution.covered_capabilities
                ),
                "uncovered_capabilities": sorted(
                    resolution.uncovered_capabilities
                ),
                "covered_modalities": sorted(
                    item.value
                    for item in resolution.covered_modalities
                ),
                "uncovered_modalities": sorted(
                    item.value
                    for item in resolution.uncovered_modalities
                ),
                "estimated_disk_mb": resolution.estimated_disk_mb,
                "estimated_vram_mb": resolution.estimated_vram_mb,
                "hardware_budget": {
                    "disk_mb": hardware.disk_mb,
                    "memory_mb": hardware.memory_mb,
                    "vram_mb": hardware.vram_mb,
                    "allow_gpu_packages": hardware.allow_gpu_packages,
                },
                "alternative_plans": [
                    list(item) for item in resolution.alternative_plans
                ],
                "warnings": list(resolution.warnings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@models_app.command("download")
def download_model(
    catalog_path: Path = typer.Argument(..., exists=True, readable=True),
    model_id: str = typer.Argument(...),
    public_key: str = typer.Option(
        "",
        "--catalog-public-key",
        envvar="NOUS_MODEL_CATALOG_PUBLIC_KEY",
    ),
    allow_unsigned: bool = typer.Option(False, "--allow-unsigned"),
) -> None:
    """Download and checksum all artifacts for a catalog model."""
    catalog = _load_catalog(
        catalog_path,
        public_key,
        allow_unsigned,
    )
    model = catalog.model(model_id)
    if model is None:
        typer.echo(f"Catalog model '{model_id}' not found.", err=True)
        raise typer.Exit(code=1)
    root = _workspace_root() / "models"
    downloader = ResumableModelDownloader(
        root / "downloads" / model_id,
        journal=TransactionJournal(root / "transactions.json"),
    )
    for artifact in model.artifacts:
        path = downloader.download(artifact)
        typer.echo(f"Verified: {path}")


@models_app.command("doctor")
def models_doctor() -> None:
    """Inspect registry and incomplete distribution operations."""
    registry = _registry()
    records = registry.list(include_removed=True)
    instances = registry.list_instances()
    journal = TransactionJournal(
        _workspace_root() / "models" / "transactions.json"
    )
    broken = [
        item
        for item in records
        if item.state is ModelLifecycleState.BROKEN
    ]
    typer.echo("Unified Model Runtime")
    typer.echo(f"  Registry:     {_registry_path()}")
    typer.echo(f"  Models:       {len(records)}")
    typer.echo(f"  Instances:    {len(instances)}")
    typer.echo(f"  Broken:       {len(broken)}")
    typer.echo(f"  Recoverable:  {len(journal.incomplete())}")


def setup_command(
    path: Path = typer.Option(
        Path(".nous"),
        "--path",
        help="Nous workspace directory.",
    ),
    gui: bool = typer.Option(
        False,
        "--gui",
        help="Open the optional graphical installer.",
    ),
) -> None:
    """Prepare the local unified model runtime directories."""
    if gui:
        from nous_runtime.model_distribution.installer_gui import (
            run_gui_installer,
        )

        try:
            run_gui_installer(path)
        except Exception as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        return
    root = path.resolve()
    models_root = root / "models"
    for directory in (
        models_root,
        models_root / "downloads",
        models_root / "imported",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    registry = ModelRuntimeRegistry(models_root / "registry.json")
    registry.flush()
    typer.echo(f"Nous model runtime prepared at {models_root}")


def register_unified_model_commands(app: typer.Typer) -> None:
    app.add_typer(models_app, name="models")
    app.command("setup")(setup_command)


__all__ = [
    "models_app",
    "register_unified_model_commands",
    "setup_command",
]
