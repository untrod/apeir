"""Console entry point for the Nous Node Protocol relay."""

from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path

import typer

from nous_runtime.project.workspace import default_workspace_path

from .relay import NodeRelayServer


app = typer.Typer(name="nous-relay", help="Operate the Nous Node Protocol v1 relay.")


@app.command("init")
def init_relay(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Create or read the durable relay identity."""
    relay = NodeRelayServer(state_dir=state_dir)
    typer.echo(json.dumps({"state_dir": str(relay.state_dir), "public_key": relay.public_key}))


@app.command("trust")
def trust_node(
    node_state: Path = typer.Argument(..., exists=True, file_okay=False),
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
) -> None:
    """Trust a node's durable public identity explicitly."""
    identity_path = node_state / "identity.json"
    if not identity_path.is_file():
        raise typer.BadParameter("node state has no identity.json")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    relay = NodeRelayServer(state_dir=state_dir)
    relay.register_node(str(identity["node_id"]), str(identity["public_key"]))
    typer.echo(json.dumps({"trusted": identity["node_id"], "public_key": identity["public_key"]}))


@app.command("serve")
def serve_relay(
    state_dir: Path = typer.Option(default_workspace_path("relay"), "--state-dir"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(9771, "--port", min=1, max=65535),
    cert_file: Path | None = typer.Option(None, "--cert-file"),
    key_file: Path | None = typer.Option(None, "--key-file"),
) -> None:
    """Run the authenticated relay in the foreground."""
    context = None
    if cert_file or key_file:
        if not cert_file or not key_file:
            raise typer.BadParameter("--cert-file and --key-file must be provided together")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    relay = NodeRelayServer(
        host=host,
        port=port,
        state_dir=state_dir,
        ssl_context=context,
    )

    async def _serve() -> None:
        url = await relay.start()
        typer.echo(json.dumps({"relay_url": url, "public_key": relay.public_key}))
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
