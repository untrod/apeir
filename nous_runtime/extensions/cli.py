"""CLI for inspecting and installing ecosystem extensions."""

from __future__ import annotations

import json
import asyncio
import getpass
import os
from pathlib import Path

import typer

from nous_runtime.extensions import ExtensionInspector, ExtensionRegistry
from compat.nki_client import DEFAULT_ENDPOINT, NKIClient
from nous_runtime.extensions.admission import ExtensionAdmissionError, ExtensionAdmissionService
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.exporter import ExtensionExportError, ExtensionExporter
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.project.workspace import default_workspace_path


extension_app = typer.Typer(
    help="Inspect and install skills, plugins, MCP configs, and API extensions"
)


def _emit(value, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(value, list):
        for item in value:
            typer.echo(
                f"{item['extension_id']}\t{item['version']}\t"
                f"C{item['compatibility_level']}\t{item['state']}"
            )
        return
    if "admitted" in value:
        typer.echo(f"Extension: {value['extension_id']}")
        typer.echo(f"Admitted: {str(bool(value['admitted'])).lower()}")
        typer.echo(
            "Authority: "
            + ("kernel_grant" if value.get("granted_capabilities") else "none")
        )
        typer.echo(
            "Granted: "
            + (", ".join(value.get("granted_capabilities") or ()) or "none")
        )
        typer.echo(f"Receipt: {value.get('receipt_id') or 'none'}")
        return
    typer.echo(f"Extension: {value['extension_id']} {value['version']}")
    typer.echo(f"Format: {value['source_format']} (C{value['compatibility_level']})")
    typer.echo(f"Kinds: {', '.join(value['kinds'])}")
    requests = value.get("capabilities") or []
    typer.echo(f"Capability requests: {len(requests)} (not authorized)")


@extension_app.command("inspect")
def inspect_extension(
    source: Path,
    as_json: bool = typer.Option(False, "--json", help="Emit normalized JSON"),
):
    """Detect and normalize a source without installing or executing it."""

    try:
        manifest = ExtensionInspector().inspect(source)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(manifest.to_dict(), as_json)


@extension_app.command("validate")
def validate_extension(
    source: Path,
    as_json: bool = typer.Option(False, "--json", help="Emit normalized JSON"),
):
    """Validate a source; this performs no install, dependency, or code action."""

    inspect_extension(source, as_json)


@extension_app.command("install")
def install_extension(
    source: Path,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Copy an extension into the immutable registry with zero authority."""

    try:
        manifest = ExtensionRegistry(registry).install(source)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    result = manifest.to_dict()
    result["installed"] = True
    result["authority"] = "none"
    record = ExtensionRegistry(registry).get_record(manifest.extension_id) or {}
    result["supply_chain"] = {
        key: record.get(key, "")
        for key in (
            "normalized_ir_digest",
            "sbom_digest",
            "provenance_digest",
            "signature_status",
            "signature_digest",
        )
    }
    _emit(result, as_json)


@extension_app.command("list")
def list_extensions(
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    _emit(ExtensionRegistry(registry).list(), as_json)


@extension_app.command("verify")
def verify_extension(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Verify package, SBOM, provenance, signature state, registry, and lock."""

    extension_registry = ExtensionRegistry(registry)
    try:
        manifest = extension_registry.verify(extension_id)
        record = extension_registry.get_record(extension_id) or {}
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    result = {
        "extension_id": manifest.extension_id,
        "verified": True,
        "content_digest": record.get("digest", ""),
        "normalized_ir_digest": record.get("normalized_ir_digest", ""),
        "sbom_digest": record.get("sbom_digest", ""),
        "provenance_digest": record.get("provenance_digest", ""),
        "signature_status": record.get("signature_status", "Unknown"),
        "authority": record.get("authority", "none"),
    }
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(f"Extension: {manifest.extension_id}")
        typer.echo("Supply chain: verified")
        typer.echo(f"Signature: {result['signature_status']}")
        typer.echo(f"Authority: {result['authority']}")


@extension_app.command("sign")
def sign_extension(
    extension_id: str,
    key: Path = typer.Option(..., "--key", help="Ed25519 private key in PEM format"),
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Sign installed immutable content; the private key is never persisted."""

    try:
        result = ExtensionRegistry(registry).sign(extension_id, key)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    value = {"extension_id": extension_id, "signed": True, **result}
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(f"Extension: {extension_id}")
        typer.echo(f"Signature: {result['signature_status']}")
        typer.echo(f"Digest: {result['signature_digest']}")


@extension_app.command("export")
def export_extension(
    extension_id: str,
    target_format: str = typer.Option("skill", "--format"),
    output: Path = typer.Option(Path("."), "--output"),
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Export a verified extension without carrying any Kernel authority."""

    try:
        result = ExtensionExporter(ExtensionRegistry(registry)).export(
            extension_id,
            target_format=target_format,
            output_root=output,
        )
    except (OSError, ValueError, ExtensionExportError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    value = result.to_dict()
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    typer.echo(f"Exported: {value['package_path']}")
    typer.echo(f"Compatibility: {result.compatibility.status}")
    typer.echo(
        "Lossy fields: "
        + (", ".join(result.compatibility.lossy_fields) or "none")
    )


def _endpoint(value: str) -> str:
    return value or os.environ.get("NOUS_KERNEL_ENDPOINT", DEFAULT_ENDPOINT)


async def _with_services(registry_path: Path, endpoint: str):
    registry = ExtensionRegistry(registry_path)
    client = await NKIClient.connect(
        endpoint, principal_id=f"os-user:{getpass.getuser()}"
    )
    admission = ExtensionAdmissionService(registry, client)
    permissions = ExtensionPermissionService(
        registry,
        admission,
        ApprovalBroker(GovernanceStore(registry_path.parent / "governance")),
    )
    return registry, client, admission, permissions


@extension_app.command("admit")
def admit_extension(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    endpoint: str = typer.Option("", "--kernel-endpoint"),
    as_json: bool = typer.Option(False, "--json"),
):
    async def run():
        _, client, admission, _ = await _with_services(registry, _endpoint(endpoint))
        try:
            return await admission.admit(extension_id)
        finally:
            await client.close()

    try:
        decision = asyncio.run(run())
    except (OSError, ValueError, ExtensionAdmissionError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(decision.to_dict(), as_json)


@extension_app.command("permissions")
def extension_permissions(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    as_json: bool = typer.Option(False, "--json"),
):
    extension_registry = ExtensionRegistry(registry)
    try:
        manifest = extension_registry.verify(extension_id)
        record = extension_registry.get_record(extension_id) or {}
        requested = {item.capability for item in manifest.capabilities}
        baseline = set(record.get("granted_capabilities") or ()) or set(
            record.get("previous_granted_capabilities") or ()
        )
        value = {
            "extension_id": extension_id,
            "requested": sorted(requested),
            "previously_granted": sorted(baseline),
            "added": sorted(requested - baseline),
            "removed": sorted(baseline - requested),
            "unchanged": sorted(requested & baseline),
            "approval_required": bool(requested - baseline),
        }
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(f"Extension: {extension_id}")
        typer.echo("Add: " + (", ".join(value["added"]) or "none"))
        typer.echo("Remove: " + (", ".join(value["removed"]) or "none"))
        typer.echo("Unchanged: " + (", ".join(value["unchanged"]) or "none"))


@extension_app.command("approve")
def approve_extension(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    endpoint: str = typer.Option("", "--kernel-endpoint"),
    approver: str = typer.Option("", "--approver"),
    as_json: bool = typer.Option(False, "--json"),
):
    async def run():
        extension_registry, client, admission, permissions = await _with_services(
            registry, _endpoint(endpoint)
        )
        try:
            if extension_registry.read_admission(extension_id) is None:
                await admission.admit(extension_id)
            context = AuthorizationContext(
                subject_type="user",
                subject_id=approver or getpass.getuser(),
                authn_method="cli_os_user",
                authn_confidence=1.0,
                session_locality="local",
            )
            _, request = permissions.request(extension_id, context)
            if request is None:
                current = extension_registry.read_admission(extension_id)
                return current
            decision = await permissions.approve(
                extension_id,
                request.request_id,
                approver or getpass.getuser(),
            )
            return decision.to_dict()
        finally:
            await client.close()

    try:
        result = asyncio.run(run())
    except (OSError, ValueError, ExtensionAdmissionError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(result, as_json)


@extension_app.command("revoke")
def revoke_extension(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
    endpoint: str = typer.Option("", "--kernel-endpoint"),
    reason: str = typer.Option("user_requested", "--reason"),
    as_json: bool = typer.Option(False, "--json"),
):
    async def run():
        _, client, _, permissions = await _with_services(registry, _endpoint(endpoint))
        try:
            return await permissions.revoke(extension_id, reason=reason)
        finally:
            await client.close()

    try:
        decision = asyncio.run(run())
    except (OSError, ValueError, ExtensionAdmissionError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(decision.to_dict(), as_json)


@extension_app.command("remove")
def remove_extension(
    extension_id: str,
    registry: Path = typer.Option(default_workspace_path("extensions"), "--registry"),
):
    if not ExtensionRegistry(registry).remove(extension_id):
        typer.echo(f"Error: extension not found: {extension_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"removed registry reference: {extension_id}")


def register_extension_commands(app: typer.Typer) -> None:
    app.add_typer(extension_app, name="extension")
