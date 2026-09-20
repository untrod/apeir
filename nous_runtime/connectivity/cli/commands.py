# -*- coding: utf-8 -*-
"""
Connectivity CLI commands.

Provides:
  nous server init/start/status
  nous node pair/join/start/status/list/show/revoke
  nous task submit/list/show/events/cancel
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from nous_runtime.node_runtime.paths import DEFAULT_NODE_STATE_DIR

_log = logging.getLogger("nous.connectivity.cli")

# Lazy imports to avoid circular dependencies


def _get_gateway():
    from ..control_plane.gateway import ControlPlaneGateway
    return ControlPlaneGateway


def _get_daemon():
    from ..node.daemon import NodeDaemon
    return NodeDaemon


def _get_registry():
    from ..control_plane.node_registry import NodeRegistry
    return NodeRegistry


def _get_task_coordinator():
    from ..control_plane.task_coordinator import TaskCoordinator
    return TaskCoordinator


# Server Commands

# Module-level gateway instance
_gateway = None


def server_init(host: str = "127.0.0.1", port: int = 9770) -> None:
    """Initialize the Control Plane."""
    global _gateway
    GW = _get_gateway()
    _gateway = GW(host=host, port=port)
    print(f"Control Plane initialized: {host}:{port}")


def server_start() -> None:
    """Start the Control Plane."""
    global _gateway
    if _gateway is None:
        print("Error: Control Plane not initialized. Run 'nous server init' first.")
        return
    _gateway.start()
    print(f"Control Plane started on {_gateway.host}:{_gateway.port}")


def server_stop() -> None:
    """Stop the Control Plane."""
    global _gateway
    if _gateway:
        _gateway.stop()
        print("Control Plane stopped.")


def server_status(json_fmt: bool = False) -> None:
    """Show Control Plane status."""
    global _gateway
    if _gateway is None:
        info = {"running": False, "error": "Not initialized"}
    else:
        info = _gateway.get_status()

    if json_fmt:
        print(json.dumps(info, indent=2))
    else:
        print(f"Control Plane: {'running' if info.get('running') else 'stopped'}")
        print(f"  Nodes: {info.get('nodes_online', 0)} online / {info.get('nodes_registered', 0)} registered")
        print(f"  Sessions: {info.get('sessions_active', 0)} active")
        print(f"  Tasks: {info.get('tasks_queued', 0)} queued, "
              f"{info.get('tasks_running', 0)} running, "
              f"{info.get('tasks_completed', 0)} completed, "
              f"{info.get('tasks_failed', 0)} failed")


# Node Commands

def node_pair() -> str:
    """Create a pairing code. Returns the code."""
    global _gateway
    if _gateway is None:
        print("Error: Control Plane not running. Start it with 'nous server start' first.")
        return ""
    code = _gateway.pairing.create_code()
    print(f"Pairing code: {code}")
    print("Expires in 5 minutes. Share this ONLY with a device you trust.")
    return code


def node_join(code: str, name: str = "node", cp_host: str = "127.0.0.1", cp_port: int = 9770) -> bool:
    """Join a Control Plane using a pairing code."""
    from ..protocol.identity import NodeIdentity

    # Generate a simple identity
    import platform
    import secrets
    pk = secrets.token_hex(32)  # Simplified: random key as identity

    identity = NodeIdentity.create(
        node_name=name,
        node_role="personal_node",
        platform_os=platform.system(),
        platform_os_version=platform.release(),
        platform_arch=platform.machine(),
        platform_hostname=platform.node(),
        public_key=pk,
        capabilities=["system.echo"],
    )

    NodeD = _get_daemon()
    daemon = NodeD(
        control_plane_host=cp_host,
        control_plane_port=cp_port,
        node_name=name,
    )

    success = daemon.pair(code, identity)
    if success:
        print(f"Node '{name}' paired successfully. Node ID: {identity.node_id}")
        return True
    else:
        print("Pairing failed. Check the code and try again.")
        return False


def node_start(name: str = "node", cp_host: str = "127.0.0.1", cp_port: int = 9770) -> None:
    """Start the Node daemon."""
    NodeD = _get_daemon()
    daemon = NodeD(
        control_plane_host=cp_host,
        control_plane_port=cp_port,
        node_name=name,
    )
    daemon.start()
    # Wait briefly for connection
    time.sleep(0.5)
    status = daemon.get_status()
    print(f"Node daemon started: {status['control_plane']}")
    print(f"  Connected: {status['connected']}")
    print(f"  Capabilities: {', '.join(status['capabilities'])}")


def _local_node_status(state_dir: str | Path = DEFAULT_NODE_STATE_DIR) -> dict | None:
    path = Path(state_dir).expanduser().resolve() / "status.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def node_status(
    json_fmt: bool = False, state_dir: str | Path = DEFAULT_NODE_STATE_DIR
) -> None:
    """Show Node status."""
    local = _local_node_status(state_dir)
    if local is not None:
        info = {"local_node": local}
    # Compatibility fallback for the in-process Control Plane.
    else:
        global _gateway
        if _gateway is None:
            info = {"error": "No local Node status and Control Plane is not running"}
        else:
            nodes = _get_registry().list_all()
            info = {"nodes": nodes}

    if json_fmt:
        print(json.dumps(info, indent=2, default=str))
    else:
        if "local_node" in info:
            node = info["local_node"]
            print(f"Node: {node.get('node_name', '?')} ({node.get('node_id', '?')})")
            print(f"  State: {node.get('state', 'UNKNOWN')}")
            print(f"  Heartbeat: {node.get('last_heartbeat', 'never')}")
            print(f"  Devices: {len(node.get('devices') or [])}")
            print(f"  Telemetry: {node.get('telemetry', 'UNKNOWN')}")
        elif "error" in info:
            print(info["error"])
        else:
            for n in info.get("nodes", []):
                status_marker = "[UP]" if n.get("is_online") else "[DOWN]"
                print(f"{status_marker} {n.get('node_name', '?')} ({n.get('node_id', '?')}) "
                      f"[{n.get('credential_status', '?')}]")


def node_list(
    json_fmt: bool = False, state_dir: str | Path = DEFAULT_NODE_STATE_DIR
) -> None:
    """List all paired nodes."""
    nodes = _get_registry().list_all()
    local = _local_node_status(state_dir)
    if local is not None and not any(
        item.get("node_id") == local.get("node_id") for item in nodes
    ):
        nodes.insert(
            0,
            {
                "node_id": local.get("node_id", ""),
                "node_name": local.get("node_name", ""),
                "node_role": "personal_node",
                "is_online": local.get("state") == "ONLINE",
                "credential_status": "local-identity",
                "capabilities": [
                    "system.echo",
                    "node.resource-report",
                    "node.device-report",
                ],
                "resources": local.get("resources", {}),
                "devices": local.get("devices", []),
                "last_heartbeat": local.get("last_heartbeat", ""),
            },
        )
    if json_fmt:
        print(json.dumps(nodes, indent=2, default=str))
    else:
        if not nodes:
            print("No nodes registered.")
            return
        for n in nodes:
            status_marker = "[UP]" if n.get("is_online") else "[DOWN]"
            print(f"{status_marker} {n.get('node_name', '?')}")
            print(f"    ID: {n.get('node_id', '?')}")
            print(f"    Role: {n.get('node_role', '?')}")
            print(f"    Status: {n.get('credential_status', '?')}")
            print(f"    Capabilities: {n.get('capabilities', [])}")


def node_show(node_id: str, json_fmt: bool = False) -> None:
    """Show a specific node."""
    node = _get_registry().get(node_id)
    if not node:
        print(f"Node '{node_id}' not found.")
        return
    if json_fmt:
        print(json.dumps(node, indent=2, default=str))
    else:
        for k, v in node.items():
            print(f"  {k}: {v}")


def node_revoke(node_id: str) -> None:
    """Revoke a node's credentials."""
    if _get_registry().revoke(node_id):
        print(f"Node '{node_id}' revoked.")
    else:
        print(f"Failed to revoke node '{node_id}'.")


# Task Commands

def task_submit(capability_id: str, message: str = "",
                target_node: str = "", deadline: str = "",
                json_fmt: bool = False) -> None:
    """Submit a task."""
    global _gateway
    if _gateway is None:
        print("Error: Control Plane not running.")
        return

    params = {"message": message} if capability_id == "system.echo" else {}
    task = _gateway.submit_task(
        capability_id=capability_id,
        params=params,
        target_node=target_node,
        deadline=deadline,
    )

    if task:
        if json_fmt:
            print(json.dumps(task, indent=2))
        else:
            print(f"Task submitted: {task['task_id']}")
            print(f"  Capability: {task['capability_id']}")
            print(f"  State: {task['state']}")
    else:
        print("Task submission failed.")


def task_list(state: str = "", json_fmt: bool = False) -> None:
    """List tasks."""
    tasks = _get_task_coordinator().list_all(state if state else "")
    if json_fmt:
        print(json.dumps(tasks, indent=2))
    else:
        if not tasks:
            print("No tasks.")
            return
        for t in tasks:
            marker = {
                "completed": "[OK]",
                "failed": "[FAIL]",
                "running": "[RUN]",
                "queued": "[WAIT]",
                "cancelled": "[CANCEL]",
                "expired": "[EXPIRED]",
            }.get(t.get("state", ""), "[?]")
            print(
                f"{marker} {t.get('task_id', '?')} "
                f"[{t.get('state', '?')}] {t.get('capability_id', '?')}"
            )
            if t.get("error_message"):
                print(f"    Error: {t['error_message']}")


def task_show(task_id: str, json_fmt: bool = False) -> None:
    """Show a specific task."""
    task = _get_task_coordinator().get(task_id)
    if not task:
        print(f"Task '{task_id}' not found.")
        return
    if json_fmt:
        print(json.dumps(task, indent=2))
    else:
        for k, v in task.items():
            print(f"  {k}: {v}")


def task_events(task_id: str, json_fmt: bool = False) -> None:
    """Show task events."""
    events = _get_task_coordinator().get_events(task_id)
    if json_fmt:
        print(json.dumps(events, indent=2))
    else:
        if not events:
            print("No events.")
            return
        for e in events:
            print(f"  [{e.get('event_type', '?')}] {e.get('created_at', '?')}")
            data = e.get("data_json", "{}")
            if data and data != "{}":
                print(f"    {data}")


def task_cancel(task_id: str) -> None:
    """Cancel a task."""
    if _get_task_coordinator().cancel(task_id):
        print(f"Task '{task_id}' cancelled.")
    else:
        print(f"Failed to cancel task '{task_id}'.")
