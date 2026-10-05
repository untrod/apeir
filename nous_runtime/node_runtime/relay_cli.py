"""Console entry point for the Nous Node Protocol relay."""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
from pathlib import Path

import typer

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.project.workspace import default_workspace_path

from .relay import NodeRelayServer
from .distributed_work import (
    DistributedWork,
    DistributedWorkStore,
    WorkExecutionPolicy,
    WorkRequirements,
)


app = typer.Typer(
    name="apeir-controller",
    help="Operate the APEIR Compute Mesh controller (Nous Node Protocol v1).",
)


def _controller(state_dir: Path, **options: object) -> NodeRelayServer:
    resolved = state_dir.expanduser().resolve()
    return NodeRelayServer(
        state_dir=resolved,
        artifact_store=ContentAddressedArtifactStore(resolved / "artifacts"),
        **options,
    )


def _work_store(state_dir: Path) -> DistributedWorkStore:
    return DistributedWorkStore(state_dir.expanduser().resolve())


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("execution arguments must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("execution arguments must be a JSON object")
    return parsed


def _read_node_identity(source: Path) -> dict[str, str]:
    identity_path = source / "identity.json" if source.is_dir() else source
    if not identity_path.is_file():
        raise typer.BadParameter("node identity.json was not found")
    try:
        value = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter("node identity is not valid JSON") from exc
    node_id = value.get("node_id") if isinstance(value, dict) else None
    public_key = value.get("public_key") if isinstance(value, dict) else None
    if not isinstance(node_id, str) or not isinstance(public_key, str):
        raise typer.BadParameter("node identity is missing node_id or public_key")
    return {"node_id": node_id, "public_key": public_key}


@app.command("init")
def init_relay(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Create or read the durable relay identity."""
    relay = _controller(state_dir)
    typer.echo(
        json.dumps(relay.controller_status(), ensure_ascii=False, sort_keys=True)
    )


@app.command("trust")
def trust_node(
    node_identity: Path = typer.Argument(..., exists=True),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Trust a node identity.json file (or its containing state directory)."""
    identity = _read_node_identity(node_identity)
    relay = _controller(state_dir)
    relay.register_node(str(identity["node_id"]), str(identity["public_key"]))
    typer.echo(
        json.dumps(
            {"trusted": identity["node_id"], "public_key": identity["public_key"]},
            sort_keys=True,
        )
    )


@app.command("status")
def controller_status(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Read durable Controller state without starting a listener."""
    relay = _controller(state_dir)
    typer.echo(
        json.dumps(relay.controller_status(), ensure_ascii=False, sort_keys=True)
    )


@app.command("select-node")
def select_node(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
    architecture: str = typer.Option("", "--architecture"),
    capability: str = typer.Option("", "--capability"),
) -> None:
    """Select a recently observed Node using deterministic requirements."""
    relay = _controller(state_dir)
    decision = relay.select_node(
        {"architecture": architecture, "capability": capability}
    )
    typer.echo(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not decision["selected_node"]:
        raise typer.Exit(code=2)


@app.command("submit-work")
def submit_work(
    intent: str = typer.Option(..., "--intent"),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
    architecture: list[str] | None = typer.Option(None, "--architecture"),
    operating_system: list[str] | None = typer.Option(None, "--os"),
    capability: list[str] | None = typer.Option(None, "--capability"),
    execution_capability: str = typer.Option("", "--execution-capability"),
    arguments_json: str = typer.Option("{}", "--arguments-json"),
    minimum_memory_bytes: int = typer.Option(0, "--minimum-memory-bytes", min=0),
    gpu_required: bool = typer.Option(False, "--gpu-required"),
    input_artifact: list[str] | None = typer.Option(None, "--input-artifact"),
    creator: str = typer.Option("", "--creator"),
    priority: int = typer.Option(0, "--priority", min=0, max=100),
    delivery: str = typer.Option("at_most_once", "--delivery"),
    require_receipt: bool = typer.Option(
        True, "--require-receipt/--no-require-receipt"
    ),
    work_id: str = typer.Option("", "--work-id"),
) -> None:
    """Create a durable Compute Mesh Work without dispatching it."""
    options: dict[str, object] = {}
    if work_id:
        options["work_id"] = work_id
    required_capabilities = list(capability or ())
    if execution_capability and execution_capability not in required_capabilities:
        required_capabilities.append(execution_capability)
    work = DistributedWork(
        intent=intent,
        requirements=WorkRequirements(
            architectures=tuple(architecture or ()),
            operating_systems=tuple(operating_system or ()),
            capabilities=tuple(required_capabilities),
            minimum_memory_bytes=minimum_memory_bytes,
            gpu_required=gpu_required,
        ),
        input_artifacts=tuple(input_artifact or ()),
        execution_policy=WorkExecutionPolicy(
            delivery=delivery,
            require_receipt=require_receipt,
        ),
        execution_capability=execution_capability,
        execution_arguments=_json_object(arguments_json),
        creator=creator,
        priority=priority,
        **options,
    )
    created = _work_store(state_dir).create(work)
    typer.echo(json.dumps(created.to_dict(), ensure_ascii=False, sort_keys=True))


@app.command("schedule-work")
def schedule_work(
    work_id: str = typer.Argument(...),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Place one CREATED Work using durable signed Node observations."""
    result = _controller(state_dir).schedule_work(work_id)
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["placement"]["selected_node"]:
        raise typer.Exit(code=2)


@app.command("dispatch-work")
def dispatch_work(
    work_id: str = typer.Argument(...),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Stage one ASSIGNED Work for the running Controller."""
    result = _controller(state_dir).stage_work_dispatch(work_id)
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


@app.command("reconcile-work")
def reconcile_work(
    work_id: str = typer.Argument(...),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Verify and commit one signed terminal Node result."""
    result = _controller(state_dir).reconcile_work(work_id)
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


@app.command("work-status")
def work_status(
    work_id: str = typer.Argument(""),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Read one Work or list the durable Compute Mesh Work registry."""
    store = _work_store(state_dir)
    if work_id:
        work = store.get(work_id)
        if work is None:
            typer.echo(json.dumps({"error": "Work not found", "work_id": work_id}))
            raise typer.Exit(code=2)
        typer.echo(json.dumps(work.to_dict(), ensure_ascii=False, sort_keys=True))
        return
    typer.echo(
        json.dumps(
            {
                "schema": "apeir.compute-mesh-work-status/v1",
                "counts": store.counts(),
                "works": [item.to_dict() for item in store.list()],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@app.command("serve")
def serve_relay(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(9771, "--port", min=1, max=65535),
    cert_file: Path | None = typer.Option(None, "--cert-file"),
    key_file: Path | None = typer.Option(None, "--key-file"),
    heartbeat_seconds: float = typer.Option(15.0, "--heartbeat-seconds", min=0.1),
) -> None:
    """Run the authenticated relay in the foreground."""
    context = None
    if cert_file or key_file:
        if not cert_file or not key_file:
            raise typer.BadParameter(
                "--cert-file and --key-file must be provided together"
            )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    relay = _controller(
        state_dir,
        host=host,
        port=port,
        ssl_context=context,
        heartbeat_seconds=heartbeat_seconds,
    )

    async def _serve() -> None:
        url = await relay.start()
        typer.echo(
            json.dumps(
                {
                    "schema": "apeir.controller-ready/v1",
                    "relay_url": url,
                    "public_key": relay.public_key,
                    "state_dir": str(relay.state_dir),
                    "artifact_store": str(relay.artifact_store.root),
                },
                sort_keys=True,
            )
        )
        sys.stdout.flush()
        try:
            await asyncio.Future()
        finally:
            await relay.stop()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


def main() -> None:
    app()


if __name__ == "__main__":
    main()
