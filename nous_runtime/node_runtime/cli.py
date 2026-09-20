"""Console entry point for the long-running Nous Node."""

from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path

import typer

from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from nous_runtime.node_runtime.paths import DEFAULT_NODE_STATE_DIR


node_daemon_app = typer.Typer(
    name="nous-node",
    help="Run the LLM-independent Nous Node service.",
    invoke_without_command=True,
)


def run_node(
    *,
    state_dir: Path,
    name: str = "",
    heartbeat_seconds: float = 15.0,
    once: bool = False,
    json_output: bool = False,
    relay_url: str = "",
    server_public_key: str = "",
    ca_file: Path | None = None,
) -> dict:
    service = NodeRuntimeService(
        NodeRuntimeConfig(
            state_dir=state_dir,
            node_name=name,
            heartbeat_seconds=heartbeat_seconds,
        )
    )
    if once:
        result = service.run_once()
        if json_output:
            typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            typer.echo(f"Node: {result['node_name']} ({result['node_id']})")
            typer.echo(f"State: {result['state']}")
            typer.echo(f"Devices: {len(result['devices'])}")
            typer.echo(f"Heartbeat: {result['heartbeat_sequence']}")
        return result
    typer.echo(f"Nous Node starting: {service.identity.node_id}")
    typer.echo(f"State directory: {service.state_dir}")
    if relay_url:
        if not server_public_key:
            raise typer.BadParameter(
                "--server-public-key is required with --relay-url"
            )
        from nous_runtime.node_runtime.relay import NodeRelayClient

        context = None
        if relay_url.lower().startswith("wss://"):
            context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        client = NodeRelayClient(
            service,
            relay_url,
            server_public_key,
            ssl_context=context,
            heartbeat_seconds=heartbeat_seconds,
        )

        async def _run_relay() -> None:
            await client.run_forever(asyncio.Event())

        typer.echo(f"Relay: {relay_url}")
        try:
            asyncio.run(_run_relay())
        except KeyboardInterrupt:
            pass
        finally:
            service.mark_stopped()
    else:
        service.run_forever()
    return json.loads(service.status_path.read_text(encoding="utf-8"))


@node_daemon_app.callback()
def node_daemon(
    state_dir: Path = typer.Option(DEFAULT_NODE_STATE_DIR, "--state-dir"),
    name: str = typer.Option("", "--name"),
    heartbeat_seconds: float = typer.Option(15.0, "--heartbeat-seconds", min=0.1),
    once: bool = typer.Option(False, "--once"),
    json_output: bool = typer.Option(False, "--json"),
    relay_url: str = typer.Option("", "--relay-url"),
    server_public_key: str = typer.Option("", "--server-public-key"),
    ca_file: Path | None = typer.Option(None, "--ca-file"),
) -> None:
    run_node(
        state_dir=state_dir,
        name=name,
        heartbeat_seconds=heartbeat_seconds,
        once=once,
        json_output=json_output,
        relay_url=relay_url,
        server_public_key=server_public_key,
        ca_file=ca_file,
    )


def main() -> None:
    node_daemon_app()


if __name__ == "__main__":
    main()
