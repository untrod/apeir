# -*- coding: utf-8 -*-
"""Context CLI — `nous context ...` commands."""

from __future__ import annotations

import json
from typing import Any

try:
    import typer
except ImportError:
    typer = None  # type: ignore

from nous_runtime.context.builder import BuildRequest, build_context
from nous_runtime.context.explain import explain_snapshot
from nous_runtime.context.models import ContextSnapshot
from nous_runtime.context.snapshot import create_snapshot, list_snapshots, restore_snapshot
from nous_runtime.context.store import ContextStore


def _echo_json(data: Any) -> None:
    """Output data as formatted JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _get_workspace() -> str:
    """Auto-detect workspace."""
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        return ws or ""
    except Exception:
        return ""



# Command implementations (callable without typer)


def cmd_context_current(
    workspace: str = "",
    intent: str = "",
    json_output: bool = False,
) -> ContextSnapshot:
    """Build and return current context."""
    ws = workspace or _get_workspace()
    request = BuildRequest(intent=intent, max_items=100)
    snapshot = build_context(request, workspace=ws)

    if json_output:
        _echo_json(snapshot.to_dict())
    else:
        print(f"Snapshot: {snapshot.id}")
        print(f"  Timestamp: {snapshot.timestamp}")
        print(f"  Items:     {snapshot.item_count}")
        print(f"  Sources:   {', '.join(snapshot.sources)}")
        print(f"  Confidence: {snapshot.confidence:.2f}")
        if intent:
            print(f"  Intent:    {intent}")

    return snapshot


def cmd_context_show(
    snapshot_id: str = "",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Show a specific snapshot or the most recent one."""
    ws = workspace or _get_workspace()
    store = ContextStore(ws)

    if snapshot_id:
        snapshot = store.get(snapshot_id)
    else:
        active = store.list(status="active", limit=1)
        snapshot = active[0] if active else None

    if snapshot is None:
        print(f"No snapshot found: {snapshot_id or '(none)'}")
        return None

    data = snapshot.to_dict()

    if json_output:
        _echo_json(data)
    else:
        print(f"Snapshot: {snapshot.id}")
        print(f"  Version:   {snapshot.version}")
        print(f"  Timestamp: {snapshot.timestamp}")
        print(f"  Status:    {snapshot.status}")
        print(f"  Items:     {snapshot.item_count}")
        print(f"  Sources:   {', '.join(snapshot.sources)}")
        print(f"  Confidence: {snapshot.confidence:.2f}")
        print(f"  Checksum:  {snapshot.checksum()}")
        if snapshot.metadata.get("intent"):
            print(f"  Intent:    {snapshot.metadata['intent']}")

    return data


def cmd_context_history(
    limit: int = 20,
    workspace: str = "",
    json_output: bool = False,
) -> list[dict[str, Any]]:
    """List context snapshot history."""
    ws = workspace or _get_workspace()
    snapshots = list_snapshots(workspace=ws, limit=limit)

    if json_output:
        _echo_json(snapshots)
    else:
        for s in snapshots:
            print(f"{s['id']}  [{s['status']}]  {s['timestamp']}  "
                  f"items={s['item_count']}  confidence={s['confidence']:.2f}  "
                  f"sources={','.join(s['sources'])}")

    return snapshots


def cmd_context_timeline(
    limit: int = 50,
    workspace: str = "",
    json_output: bool = False,
) -> list[dict[str, Any]]:
    """Show context timeline (all snapshots in chronological order)."""
    ws = workspace or _get_workspace()
    store = ContextStore(ws)
    snapshots = store.list(limit=limit, order="ASC")

    timeline = [
        {
            "id": s.id,
            "timestamp": s.timestamp,
            "status": s.status,
            "item_count": s.item_count,
            "confidence": s.confidence,
            "intent": s.metadata.get("intent", s.runtime.get("intent", "")),
        }
        for s in snapshots
    ]

    if json_output:
        _echo_json(timeline)
    else:
        for t in timeline:
            marker = "●" if t["status"] == "active" else "○"
            print(f"{marker} {t['timestamp']}  {t['id']}  "
                  f"items={t['item_count']}  intent='{t['intent']}'")

    return timeline


def cmd_context_explain(
    snapshot_id: str = "",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Explain a context snapshot — why it was built, what was selected."""
    ws = workspace or _get_workspace()
    store = ContextStore(ws)

    if snapshot_id:
        snapshot = store.get(snapshot_id)
    else:
        active = store.list(status="active", limit=1)
        snapshot = active[0] if active else None

    if snapshot is None:
        print(f"No snapshot found: {snapshot_id or '(none)'}")
        return None

    exp = explain_snapshot(snapshot)
    data = exp.to_dict()

    if json_output:
        _echo_json(data)
    else:
        print(f"Snapshot: {snapshot.id}")
        print(f"  Intent:   {exp.build_intent}")
        print(f"  Summary:  {exp.build_summary}")
        print()
        print(f"  Selected: {exp.selected_summary}")
        print(f"  Sources used:    {', '.join(exp.sources_used)}")
        print(f"  Sources missing: {', '.join(exp.sources_missing) if exp.sources_missing else '(none)'}")
        print(f"  Confidence: {exp.confidence:.2f} — {exp.confidence_explanation}")
        print()
        print("  Reasoning:")
        for r in exp.reasoning:
            print(f"    • {r}")

    return data


def cmd_context_snapshot(
    intent: str = "manual_snapshot",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any]:
    """Create a new context snapshot checkpoint."""
    ws = workspace or _get_workspace()
    snapshot = create_snapshot(workspace=ws, intent=intent)
    data = snapshot.to_dict()

    if json_output:
        _echo_json(data)
    else:
        print(f"Snapshot created: {snapshot.id}")
        print(f"  Items:     {snapshot.item_count}")
        print(f"  Sources:   {', '.join(snapshot.sources)}")
        print(f"  Confidence: {snapshot.confidence:.2f}")
        print(f"  Checksum:  {snapshot.checksum()}")

    return data


def cmd_context_restore(
    snapshot_id: str = "",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any]:
    """Restore context from a snapshot."""
    ws = workspace or _get_workspace()
    result = restore_snapshot(snapshot_id=snapshot_id, workspace=ws)
    data = result.to_dict()

    if json_output:
        _echo_json(data)
    else:
        if result.success:
            print(f"Restored: {result.snapshot_id}")
            print(f"  Items:   {result.restored_items}")
            print(f"  Duration: {result.duration_ms} ms")
            if result.missing_sources:
                print(f"  Missing:  {', '.join(result.missing_sources)}")
        else:
            print(f"Restore failed: {result.errors}")

    return data



# Typer app (optional — graceful when typer not available)


def register_context_commands(parent_app: Any, inspect_app: Any | None = None) -> None:
    """Register `nous context` and `nous inspect context` commands.

    Args:
        parent_app: The root typer.Typer app.
        inspect_app: The `nous inspect` typer.Typer app.
    """
    if typer is None:
        return

    context_app = typer.Typer(help="Context Runtime commands")
    parent_app.add_typer(context_app, name="context")

    # nous context current
    @context_app.command("current")
    def _current(
        intent: str = typer.Option("", "--intent", help="What you're trying to do"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Build and show the current context snapshot."""
        cmd_context_current(intent=intent, json_output=json_out)

    # nous context show
    @context_app.command("show")
    def _show(
        snapshot_id: str = typer.Option("", "--id", help="Snapshot ID (default: most recent)"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Show a context snapshot."""
        cmd_context_show(snapshot_id=snapshot_id, json_output=json_out)

    # nous context history
    @context_app.command("history")
    def _history(
        limit: int = typer.Option(20, "--limit", help="Number of snapshots"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """List context snapshot history."""
        cmd_context_history(limit=limit, json_output=json_out)

    # nous context timeline
    @context_app.command("timeline")
    def _timeline(
        limit: int = typer.Option(50, "--limit", help="Number of entries"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Show context timeline in chronological order."""
        cmd_context_timeline(limit=limit, json_output=json_out)

    # nous context explain
    @context_app.command("explain")
    def _explain(
        snapshot_id: str = typer.Option("", "--id", help="Snapshot ID (default: most recent)"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Explain a context snapshot — why and what was selected."""
        cmd_context_explain(snapshot_id=snapshot_id, json_output=json_out)

    # nous context snapshot
    @context_app.command("snapshot")
    def _snapshot(
        intent: str = typer.Option("manual_snapshot", "--intent", help="Reason for snapshot"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Create a context snapshot checkpoint."""
        cmd_context_snapshot(intent=intent, json_output=json_out)

    # nous context restore
    @context_app.command("restore")
    def _restore(
        snapshot_id: str = typer.Option("", "--id", help="Snapshot ID (default: most recent)"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Restore context from a snapshot."""
        cmd_context_restore(snapshot_id=snapshot_id, json_output=json_out)

    # nous inspect context
    if inspect_app is not None:
        context_inspect_app = typer.Typer(help="Inspect context runtime state", invoke_without_command=True)
        inspect_app.add_typer(context_inspect_app, name="context")

        @context_inspect_app.callback(invoke_without_command=True)
        def _inspect_context(ctx: typer.Context):
            """Inspect context runtime — sources, ranking, permissions, confidence."""
            if ctx.invoked_subcommand is not None:
                return
            ws = _get_workspace()
            store = ContextStore(ws)
            stats = store.stats()
            active = store.list(status="active", limit=5)

            print("Context Runtime Inspector")
            print("-" * 40)
            print(f"  DB path:        {stats.get('db_path', '?')}")
            print(f"  Total snapshots: {stats.get('total_snapshots', 0)}")
            print(f"  Active:          {stats.get('active_snapshots', 0)}")
            print(f"  Audit entries:   {stats.get('audit_entries', 0)}")
            print()

            if active:
                print("Recent active snapshots:")
                for s in active:
                    print(f"  {s.id}")
                    print(f"    timestamp:  {s.timestamp}")
                    print(f"    items:      {s.item_count}")
                    print(f"    sources:    {', '.join(s.sources)}")
                    print(f"    confidence: {s.confidence:.2f}")
                    print(f"    checksum:   {s.checksum()[:16]}...")
                    print()
            else:
                print("No active snapshots found.")

        @context_inspect_app.command("sources")
        def _inspect_sources():
            """Show context sources with health."""
            from nous_runtime.context.providers.memory import MemoryProvider
            from nous_runtime.context.providers.project import ProjectProvider
            from nous_runtime.context.providers.agent import AgentProvider
            from nous_runtime.context.providers.device import DeviceProvider
            from nous_runtime.context.providers.decision import DecisionProvider

            ws = _get_workspace()
            providers = [
                MemoryProvider(ws),
                ProjectProvider(ws),
                AgentProvider(ws),
                DeviceProvider(ws),
                DecisionProvider(ws),
            ]

            print("Context Sources")
            print("-" * 60)
            for p in providers:
                h = p.health()
                status = "✓" if h.available else "✗"
                print(f"  {status} {h.source:12s}  items={h.item_count:5d}  "
                      f"last={h.last_collected_at or 'never':20s}  "
                      f"{'ERR: ' + h.error if h.error else ''}")

        @context_inspect_app.command("audit")
        def _inspect_audit(
            snapshot_id: str = typer.Option("", "--snapshot", help="Filter by snapshot ID"),
            limit: int = typer.Option(50, "--limit", help="Max audit entries"),
        ):
            """Show context access audit log."""
            ws = _get_workspace()
            store = ContextStore(ws)
            entries = store.get_audit_log(snapshot_id=snapshot_id, limit=limit)

            if not entries:
                print("No audit entries found.")
                return

            print("Context Audit Log")
            print("-" * 80)
            for e in entries:
                print(f"  {e.get('timestamp', '?')}  actor={e.get('actor', '?')}  "
                      f"snapshot={e.get('snapshot_id', '?')}  "
                      f"decision={e.get('decision', '?')}  purpose={e.get('purpose', '?')}")
