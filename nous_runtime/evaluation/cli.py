# -*- coding: utf-8 -*-
"""Evaluation CLI — `nous evaluate ...` commands."""

from __future__ import annotations

import json
from typing import Any

try:
    import typer
except ImportError:
    typer = None  # type: ignore

from nous_runtime.evaluation.evaluator import EvaluationEngine
from nous_runtime.evaluation.history import EvaluationHistory
from nous_runtime.evaluation.models import EvaluationRecord


def _echo_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _get_workspace() -> str:
    try:
        from nous_runtime.project.workspace import find_workspace
        return find_workspace() or ""
    except Exception:
        return ""


def _print_record(record: EvaluationRecord) -> None:
    """Pretty-print an evaluation record."""
    score_pct = int(record.composite_score * 100)
    status_icon = {"pass": "✓", "fail": "✗", "warning": "⚠", "retry_required": "↻", "human_review": "👁"}

    print(f"Evaluation: {record.id}")
    print(f"  Target:    {record.target_type}/{record.target_id}")
    print(f"  Status:    {status_icon.get(record.status, '?')} {record.status.upper()}")
    print(f"  Score:     {score_pct}/100")
    print(f"  Confidence: {record.confidence:.2f}")
    print(f"  Recommendation: {record.recommendation}")
    print()
    print("  Dimensions:")
    for d in record.dimensions:
        icon = "✓" if d.passed else "✗"
        print(f"    {icon} {d.dimension:20s} {int(d.score*100):3d}%  (weight={d.weight:.2f})")
    print()
    if record.issues:
        print("  Issues:")
        for i in record.issues:
            print(f"    • {i}")
    if record.warnings:
        print("  Warnings:")
        for w in record.warnings:
            print(f"    • {w}")



# Command implementations


def cmd_evaluate_task(
    task_id: str,
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Evaluate a task."""
    ws = workspace or _get_workspace()
    engine = EvaluationEngine(workspace=ws)
    record = engine.evaluate(
        target_type="task", target_id=task_id,
        input_summary=f"Task evaluation: {task_id}",
    )
    report = engine.report(record)

    if json_output:
        _echo_json(report)
    else:
        _print_record(record)

    return report


def cmd_evaluate_agent(
    agent_id: str,
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Evaluate an agent."""
    ws = workspace or _get_workspace()
    engine = EvaluationEngine(workspace=ws)
    record = engine.evaluate(
        target_type="agent", target_id=agent_id,
        input_summary=f"Agent evaluation: {agent_id}",
    )
    report = engine.report(record)

    if json_output:
        _echo_json(report)
    else:
        _print_record(record)

    return report


def cmd_evaluate_project(
    project_id: str = "",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Evaluate a project."""
    ws = workspace or _get_workspace()
    engine = EvaluationEngine(workspace=ws)
    record = engine.evaluate(
        target_type="project", target_id=project_id or "current",
        input_summary="Project evaluation",
    )
    report = engine.report(record)

    if json_output:
        _echo_json(report)
    else:
        _print_record(record)

    return report


def cmd_evaluate_report(
    record_id: str,
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Show a specific evaluation report."""
    ws = workspace or _get_workspace()
    history = EvaluationHistory(ws)
    record = history.get(record_id)

    if record is None:
        print(f"Evaluation record not found: {record_id}")
        return None

    engine = EvaluationEngine(workspace=ws)
    report = engine.report(record)

    if json_output:
        _echo_json(report)
    else:
        _print_record(record)

    return report


def cmd_evaluate_benchmark(
    agent_id: str = "",
    workspace: str = "",
    json_output: bool = False,
) -> dict[str, Any] | None:
    """Run benchmark evaluation."""
    from nous_runtime.evaluation.benchmark import BenchmarkRunner, coding_benchmark_suite

    runner = BenchmarkRunner()
    runner.add_tasks(coding_benchmark_suite())

    if agent_id:
        profile = runner.build_profile(agent_id)
        data = profile.to_dict()
        if json_output:
            _echo_json(data)
        else:
            print(f"Agent: {agent_id}")
            print(f"  Rating:      {profile.rating}")
            print(f"  Success Rate: {profile.success_rate:.0%}")
            print(f"  Avg Score:    {profile.avg_score:.2f}")
            print(f"  Avg Latency:  {profile.avg_latency_ms:.0f}ms")
            print(f"  Avg Cost:     ${profile.avg_cost_usd:.4f}")
            if profile.category_results:
                print("  Categories:")
                for cat, stats in profile.category_results.items():
                    print(f"    {cat}: {stats['success_rate']:.0%} success, avg score {stats['avg_score']:.2f}")
        return data
    else:
        print("No agent specified. Available benchmark tasks:")
        for task in runner.list_tasks():
            print(f"  {task.task_id:25s} [{task.category:15s}] {task.description}")
        return {"tasks": len(runner.list_tasks())}



# Typer registration


def register_evaluation_commands(parent_app: Any, inspect_app: Any | None = None) -> None:
    """Register `nous evaluate` and `nous inspect evaluation` commands."""
    if typer is None:
        return

    eval_app = typer.Typer(help="Evaluation Runtime commands")
    parent_app.add_typer(eval_app, name="evaluate")

    @eval_app.command("task")
    def _task(
        task_id: str = typer.Argument(..., help="Task ID to evaluate"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Evaluate a task."""
        cmd_evaluate_task(task_id=task_id, json_output=json_out)

    @eval_app.command("agent")
    def _agent(
        agent_id: str = typer.Argument(..., help="Agent ID to evaluate"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Evaluate an agent."""
        cmd_evaluate_agent(agent_id=agent_id, json_output=json_out)

    @eval_app.command("project")
    def _project(
        project_id: str = typer.Option("", "--id", help="Project ID (default: current)"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Evaluate the current project."""
        cmd_evaluate_project(project_id=project_id, json_output=json_out)

    @eval_app.command("report")
    def _report(
        record_id: str = typer.Argument(..., help="Evaluation record ID"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Show an evaluation report."""
        cmd_evaluate_report(record_id=record_id, json_output=json_out)

    @eval_app.command("benchmark")
    def _benchmark(
        agent_id: str = typer.Option("", "--agent", help="Agent ID"),
        json_out: bool = typer.Option(False, "--json", help="JSON output"),
    ):
        """Run benchmark evaluation."""
        cmd_evaluate_benchmark(agent_id=agent_id, json_output=json_out)

    # -- Inspector --
    if inspect_app is not None:
        eval_inspect = typer.Typer(help="Inspect evaluation runtime", invoke_without_command=True)
        inspect_app.add_typer(eval_inspect, name="evaluation")

        @eval_inspect.callback(invoke_without_command=True)
        def _inspect(ctx: typer.Context):
            """Inspect evaluation runtime state."""
            if ctx.invoked_subcommand is not None:
                return
            ws = _get_workspace()
            history = EvaluationHistory(ws)
            stats = history.stats()

            print("Evaluation Runtime Inspector")
            print("-" * 40)
            print(f"  DB path:       {stats.get('db_path', '?')}")
            print(f"  Total records:  {stats.get('total_records', 0)}")
            print(f"  Passed:         {stats.get('passed', 0)}")
            print(f"  Pass rate:      {stats.get('pass_rate', 0):.0%}")
            print(f"  Avg score:      {stats.get('avg_score', 0):.2f}")
            print()

            # Recent evaluations
            records = history.list(limit=5)
            if records:
                print("Recent evaluations:")
                for r in records:
                    status_icon = "✓" if r.passed else "✗"
                    print(f"  {status_icon} {r.id}")
                    print(f"    target: {r.target_type}/{r.target_id}")
                    print(f"    score: {int(r.composite_score*100)}/100  status: {r.status}  rec: {r.recommendation}")
                    print()
            else:
                print("No evaluation records yet.")

        @eval_inspect.command("trend")
        def _trend(
            target_type: str = typer.Option("agent", "--type", help="Target type"),
            target_id: str = typer.Option("", "--id", help="Target ID"),
            limit: int = typer.Option(20, "--limit", help="Number of records"),
        ):
            """Show evaluation trend over time."""
            ws = _get_workspace()
            history = EvaluationHistory(ws)
            trend_data = history.trend(target_type=target_type, target_id=target_id, limit=limit)

            if not trend_data:
                print("No trend data available.")
                return

            print(f"Evaluation Trend: {target_type}/{target_id or '(all)'}")
            print("-" * 60)
            for t in trend_data:
                bar = "█" * int(t["composite_score"] * 20)
                print(f"  {t['created_at']}  {int(t['composite_score']*100):3d}% {bar}  {t['status']}")
