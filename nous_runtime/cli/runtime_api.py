"""Commands for the local Runtime HTTP API used by desktop clients."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import typer


DEFAULT_RUNTIME_API_HOST = "127.0.0.1"
DEFAULT_RUNTIME_API_PORT = 8770


async def _probe_kernel(endpoint: str) -> dict:
    from compat.nki_client import NKIClient

    client = NKIClient(endpoint)
    await asyncio.wait_for(client._connect(), timeout=2.0)
    try:
        return await asyncio.wait_for(
            client.health_check(deep=True),
            timeout=2.0,
        )
    finally:
        await client.close()


def _verify_kernel_ready() -> None:
    """Require a healthy authenticated Kernel on fail-closed server modes."""
    from nous_runtime.governance.runtime_mode import should_fail_closed

    endpoint = os.environ.get("NOUS_KERNEL_ENDPOINT", "").strip()
    fail_closed = should_fail_closed(surface="server")
    if not endpoint:
        if fail_closed:
            raise RuntimeError(
                "NOUS_KERNEL_ENDPOINT is required in production server mode"
            )
        return

    try:
        result = asyncio.run(_probe_kernel(endpoint))
    except Exception as error:
        if fail_closed:
            raise RuntimeError(
                f"Kernel readiness probe failed: {type(error).__name__}: {error}"
            ) from error
        return

    node = result.get("node") or {}
    ready = result.get("healthy") is True or (
        str(result.get("state") or "").upper() == "READY"
        and str(node.get("connection") or "").upper() == "CONNECTED"
    )
    if not ready and fail_closed:
        raise RuntimeError("Kernel readiness probe reported an unhealthy Runtime")


runtime_api_app = typer.Typer(
    help="Manage the local Runtime API used by desktop and other clients."
)


@runtime_api_app.command("start")
def start_runtime_api(
    host: str = typer.Option(DEFAULT_RUNTIME_API_HOST, help="Bind host."),
    port: int = typer.Option(DEFAULT_RUNTIME_API_PORT, min=1, max=65535, help="Bind port."),
) -> None:
    """Start the Runtime API in the foreground."""
    from nous_runtime.api.server import create_server
    from nous_runtime.control_plane.auth import ControlPlaneAuth

    # Bind first. A second launch must never overwrite the active instance's
    # session token before discovering a port conflict.
    try:
        server = create_server(host=host, port=port)
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"Runtime API could not start: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # The API process owns Runtime initialization. Desktop and CLI clients
    # must see the same migrations, capabilities, workspace, and Providers.
    os.environ.setdefault("NOUS_WORKSPACE_ROOT", str(Path.cwd()))
    try:
        _verify_kernel_ready()

        from nous_runtime.cli.provider_setup import load_providers_from_config
        from nous_runtime.services.lifecycle import run_migrations, seed_capabilities
        from nous_runtime.workspace.auto_create import ensure_workspace

        workspace_result = ensure_workspace(os.environ["NOUS_WORKSPACE_ROOT"])
        if not workspace_result.get("ok", False):
            raise RuntimeError(
                str(workspace_result.get("message") or "workspace initialization failed")
            )

        run_migrations()
        seed_capabilities()
        provider_count = load_providers_from_config()

        # The Runtime API owns the process-level model call path. Provider
        # registrations are not usable by Chat until the unified Gateway has
        # been composed from them.
        from nous_runtime.model_runtime.factory import gateway_service

        gateway_service.clear()
        if provider_count:
            gateway_service.configure_from_providers()
    except Exception as exc:
        server.server_close()
        typer.echo(f"Runtime API initialization failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    session_auth = None
    if not (
        os.environ.get("NOUS_API_TOKEN")
        or os.environ.get("NOUS_AUTH_TOKEN")
    ):
        try:
            session_auth = ControlPlaneAuth.get()
            session_auth.generate()
        except OSError as exc:
            server.server_close()
            typer.echo(f"Runtime API could not establish a local session: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    address, actual_port = server.server_address[:2]
    typer.echo(f"Nous Runtime API listening on http://{address}:{actual_port}")
    typer.echo("Authentication: local bearer session")

    typer.echo("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopping Nous Runtime API.")
    finally:
        server.server_close()
        if session_auth is not None:
            session_auth.revoke()


@runtime_api_app.command("token-path", hidden=True)
def runtime_api_token_path() -> None:
    """Print the local session-token path for trusted desktop integration."""
    from nous_runtime.control_plane.auth import session_token_path

    typer.echo(session_token_path())


@runtime_api_app.command("status")
def runtime_api_status(
    url: str = typer.Option(
        f"http://{DEFAULT_RUNTIME_API_HOST}:{DEFAULT_RUNTIME_API_PORT}",
        help="Runtime API base URL.",
    ),
    timeout: float = typer.Option(2.0, min=0.1, max=30.0, help="Request timeout."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Check whether the Runtime API is reachable."""
    endpoint = f"{url.rstrip('/')}/api/v1/health"
    request = Request(endpoint, headers={"Accept": "application/json"})
    result: dict[str, object]
    exit_code = 0
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "ok": bool(payload.get("ok")),
            "url": url.rstrip("/"),
            "health": payload.get("data", {}),
        }
        if not result["ok"]:
            exit_code = 1
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "url": url.rstrip("/"), "error": str(exc)}
        exit_code = 1

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["ok"]:
        typer.echo(f"Runtime API: reachable at {result['url']}")
    else:
        typer.echo(f"Runtime API: unavailable at {result['url']}", err=True)
        typer.echo("Start it with: nous runtime-api start", err=True)
    if exit_code:
        raise typer.Exit(code=exit_code)
