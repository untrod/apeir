# -*- coding: utf-8 -*-
"""
Intelligence CLI Commands — goal-oriented interaction.

Adds /goal, /plan, /run, /history, /experience commands.
"""

from __future__ import annotations


def cmd_goal(args: list[str]) -> str:
    """Create and execute a goal through the decision pipeline."""
    if not args:
        return "Usage: /goal <objective>\nExample: /goal analyze this project"

    objective = " ".join(args)
    from nous_runtime.cli.stream import Spinner

    spinner = Spinner("Understanding goal...")
    spinner.start()

    try:
        from nous_runtime.planner.pipeline import DecisionPipeline
        pipeline = DecisionPipeline()
        result = pipeline.run(objective)

        spinner.stop("done" if result.success else "failed")

        lines = [f"Goal: {result.goal.objective}",
                 f"Status: {result.goal.status.value}",
                 f"Plan: {result.plan.progress() if result.plan else 'N/A'}",
                 f"Score: {result.evaluation.score if result.evaluation else 'N/A'}",
                 f"Duration: {result.total_duration_ms:.0f}ms",
                 f"Trace: {result.trace_id}", ""]

        if result.plan:
            for t in result.plan.tasks:
                icon = "✓" if t.status.value == "completed" else "○" if t.status.value == "pending" else "✗"
                lines.append(f"  {icon} {t.description}")

        if result.errors:
            lines.append(f"\nErrors: {result.errors}")

        return "\n".join(lines)
    except Exception as e:
        spinner.stop("failed")
        return f"Goal execution failed: {e}"


def cmd_plan(args: list[str]) -> str:
    """Show the current plan or create one."""
    if not args:
        return "Usage: /plan <objective>\nExample: /plan check system health"

    objective = " ".join(args)
    from nous_runtime.planner.pipeline import DecisionPipeline

    pipeline = DecisionPipeline()
    result = pipeline.run(objective, auto_execute=False)

    if not result.plan:
        return "Could not generate plan."

    lines = [f"Plan for: {objective}", ""]
    for i, t in enumerate(result.plan.tasks, 1):
        deps = f" (depends: {', '.join(t.depends_on)})" if t.depends_on else ""
        lines.append(f"  {i}. {t.description} → {t.capability_id or 'auto'}{deps}")

    lines.append(f"\nTotal: {len(result.plan.tasks)} tasks")
    lines.append("Run /run to execute this plan.")
    return "\n".join(lines)


def cmd_run(args: list[str]) -> str:
    """Execute a plan (requires /goal or /plan first)."""
    from nous_runtime.cli.stream import Spinner

    spinner = Spinner("Executing...")
    spinner.start()

    try:
        from nous_runtime.planner.dispatcher import Dispatcher
        from nous_runtime.planner.plan import Plan

        # Create a quick plan from args or use last goal
        objective = " ".join(args) if args else "system health check"
        plan = Plan(goal_id="cli_run")
        plan.add_task(
            description=f"Execute: {objective}",
            capability_id="model.reason",
            prompt=objective,
        )

        dispatcher = Dispatcher()
        result = dispatcher.dispatch_plan(plan)
        spinner.stop("done" if result["success"] else "failed")

        return (
            f"Execution: {'✓' if result['success'] else '✗'}\n"
            f"Tasks: {result['progress']['done']}/{result['progress']['total']} done\n"
            f"Failed: {result['progress']['failed']}"
        )
    except Exception as e:
        spinner.stop("failed")
        return f"Execution failed: {e}"


def cmd_history(args: list[str]) -> str:
    """Show execution history from experience store."""
    try:
        from nous_runtime.learning.experience import query
        records = query(limit=20)

        if not records:
            return "No execution history recorded."

        lines = [f"{'Capability':<24} {'Provider':<16} {'Status':<8} {'Time'}", "─" * 60]
        for r in records[-15:]:
            cap = r.get("capability_id", "?")[:22]
            prov = r.get("provider_id", "?")[:14]
            status = "✓" if r.get("ok") else "✗"
            dur = f"{r.get('duration_ms', 0):.0f}ms"
            lines.append(f"{cap:<24} {prov:<16} {status:<8} {dur}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def cmd_experience(args: list[str]) -> str:
    """Show provider rankings from experience."""
    try:
        from nous_runtime.learning.optimizer import provider_rankings, optimization_suggestions

        rankings = provider_rankings()
        if not rankings:
            return "No experience data yet."

        lines = ["Provider Rankings (by success rate):", ""]
        lines.append(f"{'Provider':<20} {'Success':<10} {'Avg Latency':<14} {'Samples'}")
        lines.append("─" * 54)
        for r in rankings[:10]:
            lines.append(
                f"{r['provider_id']:<20} {r['success_rate']:.1%}     "
                f"{r['avg_duration_ms']:.0f}ms        {r['sample_size']}"
            )

        # Optimization suggestions
        suggestions = optimization_suggestions()
        if suggestions:
            lines.append(f"\nSuggestions ({len(suggestions)}):")
            for s in suggestions:
                lines.append(f"  • {s.get('recommendation', s['type'])}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
