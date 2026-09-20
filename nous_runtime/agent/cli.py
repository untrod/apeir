# -*- coding: utf-8 -*-
"""Agent Runtime CLI commands."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from nous_runtime.agent.lifecycle import transition
from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import AgentState
from nous_runtime.agent.registry import AgentRegistry

agent_app = typer.Typer(help="Manage runtime Agents")


def _registry() -> AgentRegistry:
    try:
        from nous_runtime.project.workspace import find_workspace

        workspace = find_workspace()
        if workspace:
            return AgentRegistry(workspace)
    except Exception as exc:
        logging.debug("Could not initialize agent registry from workspace: %s", exc)
    return AgentRegistry(Path(".nous"))


def _print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True))


@agent_app.command("register")
def register_cmd(
    name: str = typer.Argument(..., help="Agent name"),
    capability: list[str] = typer.Option(None, "--capability", "-c", help="Bound capability ID"),
    permission: list[str] = typer.Option(None, "--permission", "-p", help="Required permission"),
    description: str = typer.Option("", "--description", help="Agent description"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    manifest = build_agent_manifest(
        name,
        description=description,
        capabilities=tuple(capability or ()),
        permissions=tuple(permission or ()),
    )
    profile = _registry().register(manifest)
    if json_output:
        _print_json(profile.to_dict())
    else:
        typer.echo(f"Agent registered: {profile.agent_id}")


@agent_app.command("list")
def list_cmd(json_output: bool = typer.Option(False, "--json", help="JSON output")):
    profiles = _registry().list()
    if json_output:
        _print_json([item.to_dict() for item in profiles])
        return
    if not profiles:
        typer.echo("No agents registered.")
        return
    for profile in profiles:
        typer.echo(f"{profile.agent_id} [{profile.state.value}] {profile.manifest.identity.name}")


@agent_app.command("show")
def show_cmd(agent_id: str, json_output: bool = typer.Option(False, "--json", help="JSON output")):
    profile = _registry().require(agent_id)
    if json_output:
        _print_json(profile.to_dict())
        return
    typer.echo(f"Agent: {profile.agent_id}")
    typer.echo(f"State: {profile.state.value}")
    typer.echo(f"Health: {profile.health.status}")
    typer.echo(f"Capabilities: {len(profile.manifest.capabilities)}")


@agent_app.command("start")
def start_cmd(agent_id: str):
    registry = _registry()
    profile = registry.require(agent_id)
    target = AgentState.READY if profile.state == AgentState.REGISTERED else AgentState.RUNNING
    registry.save_profile(transition(profile, target))
    typer.echo(f"Agent state: {target.value}")


@agent_app.command("stop")
def stop_cmd(agent_id: str):
    registry = _registry()
    profile = registry.require(agent_id)
    registry.save_profile(transition(profile, AgentState.TERMINATED))
    typer.echo("Agent state: TERMINATED")


@agent_app.command("health")
def health_cmd(agent_id: str = typer.Argument("", help="Agent ID")):
    registry = _registry()
    profiles = [registry.require(agent_id)] if agent_id else registry.list()
    for profile in profiles:
        typer.echo(f"{profile.agent_id}: {profile.health.status} failures={profile.health.failure_count}")


@agent_app.command("explain")
def explain_cmd(agent_id: str):
    profile = _registry().require(agent_id)
    data = {
        "agent_id": profile.agent_id,
        "state": profile.state.value,
        "capabilities": [item.to_dict() for item in profile.manifest.capabilities],
        "budget": profile.manifest.budget.to_dict(),
        "governance": "Agent execution is routed through ActionProposal and ExecutionAuthorizationGate.",
    }
    _print_json(data)
