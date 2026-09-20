"""Headless model management and declarative configuration commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from nous_runtime.yaml_compat import yaml

from nous_runtime.model_distribution import (
    Ed25519CatalogVerifier,
    ModelCatalog,
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_runtime.configuration import (
    DeclarativeModelConfigService,
    ModelDefaultsStore,
)
from nous_runtime.model_runtime.models import (
    ModelEndpointType,
    ModelLifecycleState,
    ModelModality,
    ModelRequest,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.model_runtime.router import ModelRouter

config_app = typer.Typer(help="Validate and apply declarative model YAML.")


def _workspace() -> Path:
    return Path(os.environ.get("NOUS_WORKSPACE_ROOT") or ".nous")


def _registry_path() -> Path:
    return Path(
        os.environ.get("NOUS_MODEL_REGISTRY")
        or _workspace() / "models" / "registry.json"
    )


def _service() -> DeclarativeModelConfigService:
    return DeclarativeModelConfigService(_registry_path())


@config_app.command("validate")
def config_validate(
    path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    payload = _service().load(path)
    typer.echo(
        json.dumps(
            {
                "valid": True,
                "schema_version": payload["schema_version"],
                "models": len(payload.get("models") or ()),
                "providers": len(payload.get("providers") or {}),
            },
            indent=2,
        )
    )


@config_app.command("plan")
def config_plan(
    path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    service = _service()
    typer.echo(
        json.dumps(
            service.plan(service.load(path)).to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )


@config_app.command("apply")
def config_apply(
    path: Path = typer.Argument(..., exists=True, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    service = _service()
    plan = service.apply(service.load(path), dry_run=dry_run)
    typer.echo(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    )


@config_app.command("export")
def config_export(
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    payload = _service().export()
    rendered = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
    )
    if output is None:
        typer.echo(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, output)
    typer.echo(f"Exported: {output}")


def configure_model(
    model_id: str = typer.Option("", "--model-id"),
    provider_id: str = typer.Option("", "--provider"),
    endpoint: str = typer.Option("", "--endpoint"),
    capability: list[str] = typer.Option([], "--capability"),
    credential_ref: str = typer.Option("", "--credential-ref"),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Configure a model with back/cancel support in interactive mode."""
    values = {
        "model_id": model_id,
        "provider_id": provider_id,
        "endpoint": endpoint,
        "credential_ref": credential_ref,
    }
    if not non_interactive:
        values = _interactive_configuration(values)
    if not values["model_id"] or not values["provider_id"]:
        raise typer.BadParameter(
            "--model-id and --provider are required"
        )
    config = {
        "schema_version": 1,
        "providers": {
            values["provider_id"]: {
                "kind": (
                    "local_service"
                    if values["endpoint"].startswith("http://127.0.0.1")
                    or values["endpoint"].startswith("http://localhost")
                    else "cloud_api"
                ),
                "endpoint": values["endpoint"],
                "credential_ref": values["credential_ref"],
            }
        },
        "models": [
            {
                "model_id": values["model_id"],
                "display_name": values["model_id"],
                "provider_id": values["provider_id"],
                "endpoint_type": (
                    ModelEndpointType.LOCAL_SERVICE.value
                    if values["endpoint"].startswith("http://")
                    else ModelEndpointType.CLOUD_API.value
                ),
                "capabilities": capability or ["reasoning"],
                "modalities": ["text"],
                "enabled": True,
            }
        ],
        "defaults": {},
    }
    plan = _service().apply(config, dry_run=dry_run)
    typer.echo(json.dumps(plan.to_dict(), indent=2))


def remove_model(
    model_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    registry = ModelRuntimeRegistry(_registry_path())
    record = registry.require(model_id)
    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "action": "remove",
                    "model_id": model_id,
                    "state": record.state.value,
                },
                indent=2,
            )
        )
        return
    if not yes and not typer.confirm(f"Remove {model_id}?"):
        typer.echo("Cancelled.")
        return
    if record.state is ModelLifecycleState.ENABLED:
        registry.disable(model_id)
    registry.transition(model_id, ModelLifecycleState.REMOVED)
    typer.echo(f"{model_id}: removed")


def default_model(
    role: str = typer.Argument(...),
    model_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    registry = ModelRuntimeRegistry(_registry_path())
    record = registry.require(model_id)
    if not record.enabled:
        raise typer.BadParameter("default model must be enabled")
    store = ModelDefaultsStore(
        _registry_path().with_name("defaults.json")
    )
    values = store.read()
    before = values.get(role)
    values[role] = model_id
    typer.echo(
        json.dumps(
            {
                "role": role,
                "before": before,
                "after": model_id,
                "dry_run": dry_run,
            },
            indent=2,
        )
    )
    if not dry_run:
        store.write(values)


def route_model(
    capability: list[str] = typer.Option(
        ["reasoning"],
        "--capability",
    ),
    modality: list[str] = typer.Option(["text"], "--modality"),
    task_id: str = typer.Option("cli-route", "--task-id"),
) -> None:
    request = ModelRequest(
        task_id=task_id,
        required_capabilities=frozenset(capability),
        required_modalities=frozenset(
            ModelModality(item) for item in modality
        ),
    )
    decision = ModelRouter(
        ModelRuntimeRegistry(_registry_path())
    ).route(request)
    typer.echo(
        json.dumps(decision.to_dict(), ensure_ascii=False, indent=2)
    )


def verify_model(
    model_id: str = typer.Argument(...),
) -> None:
    record = ModelRuntimeRegistry(_registry_path()).require(model_id)
    errors = []
    if record.location and not Path(record.location).exists():
        errors.append("model location does not exist")
    if not record.descriptor.availability:
        errors.append("descriptor is unavailable")
    typer.echo(
        json.dumps(
            {
                "model_id": model_id,
                "ok": not errors,
                "state": record.state.value,
                "errors": errors,
                "health": dict(record.health),
            },
            indent=2,
        )
    )
    if errors:
        raise typer.Exit(code=1)


def install_model(
    catalog_path: Path = typer.Argument(..., exists=True, readable=True),
    model_id: str = typer.Argument(...),
    public_key: str = typer.Option(
        "",
        "--catalog-public-key",
        envvar="NOUS_MODEL_CATALOG_PUBLIC_KEY",
    ),
    allow_unsigned: bool = typer.Option(False, "--allow-unsigned"),
    accept_license: bool = typer.Option(False, "--accept-license"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    verifier = Ed25519CatalogVerifier(public_key) if public_key else None
    catalog = ModelCatalog.load(
        catalog_path,
        verifier=verifier,
        require_signature=not allow_unsigned,
    )
    model = catalog.model(model_id)
    if model is None:
        raise typer.BadParameter(f"catalog model not found: {model_id}")
    unapproved = [
        package.package_id
        for package in model.packages
        if not package.license_approved
    ]
    if unapproved and not accept_license:
        raise typer.BadParameter(
            "explicit --accept-license is required"
        )
    summary = {
        "model_id": model_id,
        "artifacts": [item.to_dict() for item in model.artifacts],
        "packages": [item.package_id for item in model.packages],
        "dry_run": dry_run,
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    if dry_run:
        return
    root = _workspace() / "models"
    downloader = ResumableModelDownloader(
        root / "downloads" / model_id,
        journal=TransactionJournal(root / "transactions.json"),
    )
    paths = [downloader.download(item) for item in model.artifacts]
    registry = ModelRuntimeRegistry(_registry_path())
    registry.register(
        model.descriptor,
        state=ModelLifecycleState.REGISTERED,
        source=f"catalog:{catalog.catalog_version}",
        location=str(paths[0].parent if paths else ""),
        metadata={
            "package_ids": [
                item.package_id for item in model.packages
            ]
        },
        replace_existing=registry.get(model_id) is not None,
    )


def _interactive_configuration(
    initial: dict[str, str],
) -> dict[str, str]:
    fields = [
        ("model_id", "Model ID"),
        ("provider_id", "Provider ID"),
        ("endpoint", "Endpoint"),
        ("credential_ref", "Credential reference (env:NAME)"),
    ]
    values = dict(initial)
    index = 0
    while index < len(fields):
        key, label = fields[index]
        answer = typer.prompt(
            f"{label} [type back or cancel]",
            default=values.get(key) or "",
            show_default=bool(values.get(key)),
        ).strip()
        if answer.casefold() == "cancel":
            typer.echo("Cancelled.")
            raise typer.Exit()
        if answer.casefold() == "back":
            index = max(0, index - 1)
            continue
        values[key] = answer
        index += 1
    return values


def register_phase2_model_commands(app: typer.Typer) -> None:
    app.command("configure")(configure_model)
    app.command("install")(install_model)
    app.command("remove")(remove_model)
    app.command("default")(default_model)
    app.command("route")(route_model)
    app.command("verify")(verify_model)
    app.add_typer(config_app, name="config")


__all__ = ["config_app", "register_phase2_model_commands"]
