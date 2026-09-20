# -*- coding: utf-8 -*-
"""Experience CLI — `nous experience ...` commands."""

from __future__ import annotations

import json
from typing import Any

try:
    import typer
except ImportError:
    typer = None  # type: ignore

from nous_runtime.experience.analyzer import ExperienceAnalyzer
from nous_runtime.experience.explain import explain_experience
from nous_runtime.experience.pattern import PatternEngine
from nous_runtime.experience.recommendation import RecommendationEngine
from nous_runtime.experience.store import ExperienceStore


def _echo_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _get_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace
        return find_workspace() or ""
    except Exception:
        return ""



# Commands


def cmd_experience_list(task_type: str = "", status: str = "", limit: int = 20, json_output: bool = False) -> list[dict]:
    ws = _get_workspace()
    store = ExperienceStore(ws)
    records = store.list(task_type=task_type, status=status, limit=limit)
    data = [r.to_dict() for r in records]

    if json_output:
        _echo_json(data)
    else:
        for r in records:
            icon = "✓" if r.success else "✗"
            print(f"{icon} {r.id}  [{r.status}]  {r.task_type:20s}  {r.task_summary[:60]}")
    return data


def cmd_experience_show(record_id: str, json_output: bool = False) -> dict | None:
    ws = _get_workspace()
    store = ExperienceStore(ws)
    record = store.get(record_id)
    if record is None:
        print(f"Experience not found: {record_id}")
        return None
    if json_output:
        _echo_json(record.to_dict())
    else:
        print(explain_experience(record))
    return record.to_dict()


def cmd_experience_search(query: str, limit: int = 20, json_output: bool = False) -> list[dict]:
    ws = _get_workspace()
    store = ExperienceStore(ws)
    results = store.search(query, limit=limit)
    data = [r.to_dict() for r in results]

    if json_output:
        _echo_json(data)
    else:
        print(f"Found {len(results)} experiences matching '{query}':")
        for r in results:
            icon = "✓" if r.success else "✗"
            print(f"  {icon} [{r.status}] {r.task_type}: {r.task_summary[:80]}")
    return data


def cmd_experience_patterns(pattern_type: str = "", json_output: bool = False) -> list[dict]:
    ws = _get_workspace()
    store = ExperienceStore(ws)
    engine = PatternEngine(store)
    # Discover if store is empty, otherwise list
    patterns = store.list_patterns(pattern_type=pattern_type, limit=50)
    if not patterns:
        patterns = engine.discover(min_frequency=2)
        for p in patterns:
            store.save_pattern(p)

    data = [p.to_dict() for p in patterns]
    if json_output:
        _echo_json(data)
    else:
        for p in patterns:
            print(f"[{p.pattern_type}] {p.name}")
            print(f"  frequency={p.frequency}  success_rate={p.success_rate:.0%}  confidence={p.confidence:.2f}")
    return data


def cmd_experience_recommend(task: str, json_output: bool = False) -> list[dict]:
    ws = _get_workspace()
    store = ExperienceStore(ws)
    engine = RecommendationEngine(store)
    recs = engine.recommend(task)

    data = [r.to_dict() for r in recs]
    if json_output:
        _echo_json(data)
    else:
        print(f"Recommendations for: '{task}'")
        for r in recs:
            print(f"  [{r.recommendation_type}] {r.title}")
            print(f"    confidence={r.confidence:.2f}  reason={r.reason}")
    return data


def cmd_experience_stats(json_output: bool = False) -> dict:
    ws = _get_workspace()
    analyzer = ExperienceAnalyzer(ExperienceStore(ws))
    summary = analyzer.summary()
    if json_output:
        _echo_json(summary)
    else:
        print("Experience Runtime Stats")
        print(f"  Total:      {summary.get('total_experiences', 0)}")
        print(f"  Trusted:    {summary.get('trusted', 0)}")
        print(f"  Success:    {summary.get('success_count', 0)} ({summary.get('success_rate', 0):.0%})")
        print(f"  Patterns:   {summary.get('patterns', 0)}")
        print(f"  Avg Conf:   {summary.get('avg_confidence', 0):.2f}")
    return summary



# Typer registration


def register_experience_commands(parent_app: Any, inspect_app: Any | None = None) -> None:
    if typer is None:
        return

    exp_app = typer.Typer(help="Experience Runtime commands")
    parent_app.add_typer(exp_app, name="experience")

    @exp_app.command("list")
    def _list(
        task_type: str = typer.Option("", "--type", help="Filter by task type"),
        status: str = typer.Option("", "--status", help="Filter by status"),
        limit: int = typer.Option(20, "--limit"),
        json_out: bool = typer.Option(False, "--json"),
    ):
        """List experience records."""
        cmd_experience_list(task_type=task_type, status=status, limit=limit, json_output=json_out)

    @exp_app.command("show")
    def _show(
        record_id: str = typer.Argument(..., help="Experience record ID"),
        json_out: bool = typer.Option(False, "--json"),
    ):
        """Show an experience record."""
        cmd_experience_show(record_id=record_id, json_output=json_out)

    @exp_app.command("search")
    def _search(
        query: str = typer.Argument(..., help="Search query"),
        limit: int = typer.Option(20, "--limit"),
        json_out: bool = typer.Option(False, "--json"),
    ):
        """Search experiences."""
        cmd_experience_search(query=query, limit=limit, json_output=json_out)

    @exp_app.command("patterns")
    def _patterns(
        pattern_type: str = typer.Option("", "--type", help="Pattern type filter"),
        json_out: bool = typer.Option(False, "--json"),
    ):
        """Show discovered patterns."""
        cmd_experience_patterns(pattern_type=pattern_type, json_output=json_out)

    @exp_app.command("recommend")
    def _recommend(
        task: str = typer.Argument(..., help="Task description"),
        json_out: bool = typer.Option(False, "--json"),
    ):
        """Get recommendations for a task."""
        cmd_experience_recommend(task=task, json_output=json_out)

    @exp_app.command("stats")
    def _stats(json_out: bool = typer.Option(False, "--json")):
        """Show experience statistics."""
        cmd_experience_stats(json_output=json_out)

    # Inspector
    if inspect_app is not None:
        exp_inspect = typer.Typer(help="Inspect experience runtime", invoke_without_command=True)
        inspect_app.add_typer(exp_inspect, name="experience")

        @exp_inspect.callback(invoke_without_command=True)
        def _inspect(ctx: typer.Context):
            if ctx.invoked_subcommand is not None:
                return
            cmd_experience_stats()
