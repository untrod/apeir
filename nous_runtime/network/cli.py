# -*- coding: utf-8 -*-
"""Network CLI — nous network commands."""

from __future__ import annotations

import json
from typing import Any

try:
    import typer
except ImportError:
    typer = None

from nous_runtime.network.discovery import AgentDiscovery
from nous_runtime.network.health import NetworkHealth
from nous_runtime.network.registry import NetworkRegistry


def _echo_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _get_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace
        return find_workspace() or ""
    except Exception:
        return ""


def cmd_network_list(node_type: str = "", json_output: bool = False):
    ws = _get_workspace()
    reg = NetworkRegistry(ws)
    nodes = reg.list(node_type=node_type, limit=50)
    if json_output:
        _echo_json([n.to_dict() for n in nodes])
    else:
        for n in nodes:
            icon = "●" if n.status == "online" else "○"
            print(f"{icon} {n.id}  [{n.node_type}]  {n.name}  trust={n.trust_level}")


def cmd_network_discover(capability: str = "", json_output: bool = False):
    ws = _get_workspace()
    discovery = AgentDiscovery(NetworkRegistry(ws))
    if capability:
        results = discovery.find_by_capability(capability)
    else:
        results = [type('', (), {'node': n, 'match_score': 1.0, 'reason': 'online', 'to_dict': lambda s: {'node': s.node.to_dict(), 'match_score': s.match_score, 'reason': s.reason}})() for n in discovery.list_all_online()]
    if json_output:
        _echo_json([r.to_dict() if hasattr(r, 'to_dict') else r for r in results])
    else:
        for r in results:
            n = r.node
            print(f"  {n.name} [{n.node_type}] score={r.match_score:.2f} — {r.reason}")


def cmd_network_health(json_output: bool = False):
    ws = _get_workspace()
    health = NetworkHealth(NetworkRegistry(ws))
    report = health.network_health()
    if json_output:
        _echo_json(report)
    else:
        print(f"Network Health: {report['healthy']}/{report['total_nodes']} healthy ({report['health_rate']:.0%})")


def register_network_commands(parent_app: Any, inspect_app: Any | None = None) -> None:
    if typer is None:
        return
    net_app = typer.Typer(help="Agent Network commands")
    parent_app.add_typer(net_app, name="network")

    @net_app.command("list")
    def _list(node_type: str = typer.Option("", "--type"), json_out: bool = typer.Option(False, "--json")):
        """List agent nodes on the network."""
        cmd_network_list(node_type=node_type, json_output=json_out)

    @net_app.command("discover")
    def _discover(capability: str = typer.Option("", "--capability"), json_out: bool = typer.Option(False, "--json")):
        """Discover agents by capability."""
        cmd_network_discover(capability=capability, json_output=json_out)

    @net_app.command("health")
    def _health(json_out: bool = typer.Option(False, "--json")):
        """Show network health."""
        cmd_network_health(json_output=json_out)

    if inspect_app is not None:
        net_inspect = typer.Typer(help="Inspect agent network", invoke_without_command=True)
        inspect_app.add_typer(net_inspect, name="network")

        @net_inspect.callback(invoke_without_command=True)
        def _inspect(ctx: typer.Context):
            if ctx.invoked_subcommand is not None:
                return
            ws = _get_workspace()
            discovery = AgentDiscovery(NetworkRegistry(ws))
            summary = discovery.network_summary()
            print("Agent Network Inspector")
            print(f"  Total nodes:  {summary['total_nodes']}")
            print(f"  Online:       {summary['online_nodes']}")
            print(f"  By type:      {summary['by_type']}")
            print(f"  By trust:     {summary['by_trust']}")
