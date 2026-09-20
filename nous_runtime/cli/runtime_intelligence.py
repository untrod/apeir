"""CLI entry points for Runtime Intelligence 2.0 foundations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import typer

from nous_runtime.intelligence.routing import RoutingDecision, route_capabilities
from nous_runtime.intelligence.routing_history import RoutingDecisionHistory
from nous_runtime.intelligence.scoring import (
    NoEligibleModelError,
    RoutingConstraints,
)
from nous_runtime.intelligence.task import TaskAnalyzer
from nous_runtime.model import ModelProfile, ModelRegistry, default_model_registry


intelligence_app = typer.Typer(help="Analyze Runtime tasks")
routing_app = typer.Typer(help="Test capability-aware model routing")


@intelligence_app.command("analyze")
def intelligence_analyze(
    task_id: str = typer.Argument(..., help="Runtime Task ID"),
    json_fmt: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Analyze a persisted Runtime task and suggest matching model families."""
    from nous_runtime.task.cli import get_task_manager

    task = get_task_manager().get(task_id)
    if task is None:
        typer.echo(f"Task '{task_id}' not found.", err=True)
        raise typer.Exit(code=1)
    analysis = TaskAnalyzer().analyze(task)
    decision = route_capabilities(analysis)
    payload = {
        **analysis.to_dict(),
        "suggested_models": list(decision.candidate_models),
        "selected_model": decision.selected_model,
        "routing_reason": decision.reason,
    }
    if json_fmt:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Task          {task.id}")
    typer.echo(f"Type          {analysis.task_type}")
    typer.echo(f"Complexity    {analysis.complexity}")
    typer.echo(f"Capabilities  {', '.join(analysis.required_capabilities)}")
    typer.echo(f"Suggested     {', '.join(decision.candidate_models) or 'none'}")
    typer.echo(f"Selected      {decision.selected_model or 'none'}")


@routing_app.command("test")
def routing_test(
    prompt: str = typer.Argument("Write Python code", help="Task description"),
    json_fmt: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Analyze an ad-hoc task and show deterministic model scoring."""
    analysis = TaskAnalyzer().analyze(prompt, task_id="routing-test")
    decision = route_capabilities(
        analysis,
        registry=default_model_registry(),
        mode="auto",
    )
    payload = {"task": analysis.to_dict(), "routing": decision.to_dict()}
    if json_fmt:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Task      {analysis.task_type}")
    typer.echo(f"Selected  {decision.selected_model or 'none'}")
    typer.echo(f"Score     {decision.score:.3f}")
    typer.echo(f"Reason    {decision.reason}")
    if decision.strategy is not None:
        typer.echo(f"Strategy  {decision.strategy.strategy.value}")
    typer.echo(f"Mode      {decision.routing_mode or 'legacy'}")


@routing_app.command("compare")
def routing_compare(
    task_id: str = typer.Argument(..., help="Runtime Task ID"),
    json_fmt: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Compare eligible and rejected candidates for a persisted task."""
    task = _require_task(task_id)
    analysis = TaskAnalyzer().analyze(task)
    history = RoutingDecisionHistory(_routing_history_path())
    try:
        decision = route_capabilities(
            analysis,
            registry=default_model_registry(),
            mode="adaptive",
            history=history,
        )
    except NoEligibleModelError as exc:
        payload = {
            "error": exc.error_code,
            "message": str(exc),
            "rejections": {
                key: list(value) for key, value in exc.rejections.items()
            },
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        raise typer.Exit(code=1) from exc
    if json_fmt:
        typer.echo(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
        return
    typer.echo(f"Decision    {decision.decision_id}")
    typer.echo(f"Task        {decision.task_id}")
    typer.echo(f"Selected    {decision.selected_model_id}")
    typer.echo(f"Strategy    {decision.strategy.strategy.value}")
    typer.echo(f"Confidence  {decision.confidence:.3f}")
    typer.echo("")
    typer.echo(
        "Model           Eligible  Fit     Gap     Reliability  Cost   "
        "Latency  Uncertainty  Score   Pareto"
    )
    for candidate in decision.ranked_candidates:
        breakdown = candidate.breakdown
        if breakdown is None:
            reasons = ",".join(candidate.rejection_reasons)
            typer.echo(
                f"{candidate.model_id:<15} no        -       -       "
                f"{candidate.reliability:<11.3f} -      -        -            "
                f"-       no  {reasons}"
            )
            continue
        cost = (
            f"{candidate.estimated_cost:.2f}"
            if candidate.estimated_cost is not None
            else "?"
        )
        latency = (
            str(candidate.latency_ms)
            if candidate.latency_ms is not None
            else "?"
        )
        typer.echo(
            f"{candidate.model_id:<15} yes       "
            f"{breakdown.capability_fit:<7.3f} "
            f"{breakdown.gap_penalty:<7.3f} "
            f"{candidate.reliability:<11.3f} "
            f"{cost:<6} {latency:<8} "
            f"{breakdown.uncertainty:<12.3f} "
            f"{candidate.score:<7.3f} "
            f"{'yes' if candidate.pareto_optimal else 'no'}"
        )


@routing_app.command("explain")
def routing_explain(
    decision_id: str = typer.Argument(..., help="Adaptive RoutingDecision ID"),
    json_fmt: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Explain a previously recorded adaptive routing decision."""
    history = RoutingDecisionHistory(_routing_history_path())
    payload = history.get_payload(decision_id)
    if payload is None:
        typer.echo(f"Routing decision '{decision_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if json_fmt:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    decision = RoutingDecision.from_dict(payload)
    typer.echo(f"Decision    {decision.decision_id}")
    typer.echo(f"Selected    {decision.selected_model_id}")
    typer.echo(
        f"Strategy    "
        f"{decision.strategy.strategy.value if decision.strategy else 'none'}"
    )
    typer.echo(f"Confidence  {decision.confidence:.3f}")
    typer.echo(f"Policy      {decision.policy_version}")
    typer.echo(f"Profiles    {decision.profile_version}")
    typer.echo(f"Mode        {decision.routing_mode}")
    for explanation in decision.explanation:
        typer.echo(f"  - {explanation}")


@routing_app.command("simulate")
def routing_simulate(
    json_fmt: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Run deterministic built-in routing fixtures without real providers."""
    fixtures = _simulation_fixtures()
    results = []
    for fixture in fixtures:
        analysis = TaskAnalyzer().analyze(
            fixture["prompt"],
            task_id=f"simulate-{fixture['name']}",
        )
        if fixture.get("risk") is not None:
            analysis = replace(
                analysis,
                constraints={
                    **analysis.constraints,
                    "risk_level": fixture["risk"],
                },
                metadata={
                    **analysis.metadata,
                    "result_verifiable": fixture.get("verifiable", False),
                },
            )
        registry = fixture.get("registry") or default_model_registry()
        decision = route_capabilities(
            analysis,
            registry=registry,
            constraints=fixture.get("constraints"),
            mode="adaptive",
        )
        results.append(
            {
                "fixture": fixture["name"],
                "selected": decision.selected_model_id,
                "strategy": decision.strategy.strategy.value,
                "confidence": decision.confidence,
                "score": decision.score,
            }
        )
    if json_fmt:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for result in results:
        typer.echo(
            f"{result['fixture']:<20} {result['selected']:<10} "
            f"{result['strategy']:<18} "
            f"confidence={result['confidence']:.3f}"
        )


def register_runtime_intelligence_commands(app: typer.Typer) -> None:
    app.add_typer(intelligence_app, name="intelligence")
    app.add_typer(routing_app, name="routing")


def _require_task(task_id: str):
    from nous_runtime.task.cli import get_task_manager

    task = get_task_manager().get(task_id)
    if task is None:
        typer.echo(f"Task '{task_id}' not found.", err=True)
        raise typer.Exit(code=1)
    return task


def _routing_history_path() -> Path:
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    root = workspace if workspace is not None else Path.cwd() / ".nous"
    return root / "adaptive_routing_decisions.jsonl"


def _simulation_fixtures() -> list[dict[str, object]]:
    unknown_registry = ModelRegistry(
        [
            ModelProfile(
                "new-model",
                "unknown-provider",
                ("reasoning",),
                reliability_score=0.45,
            )
        ]
    )
    return [
        {"name": "coding", "prompt": "Write Python code"},
        {"name": "mathematics", "prompt": "Prove a math equation"},
        {"name": "vision", "prompt": "Analyze an image with vision"},
        {
            "name": "low_cost",
            "prompt": "Write Python code on a budget",
            "constraints": RoutingConstraints(
                required_capabilities=frozenset({"coding", "reasoning"}),
                max_cost=3.0,
            ),
        },
        {
            "name": "low_latency",
            "prompt": "Fast local code task",
            "constraints": RoutingConstraints(
                required_capabilities=frozenset(
                    {"coding", "reasoning", "local_execution"}
                ),
                max_latency_ms=1_000,
                requires_local_execution=True,
                privacy_level="local",
            ),
        },
        {"name": "private_local", "prompt": "Private local Ollama analysis"},
        {
            "name": "high_risk_review",
            "prompt": "Review and publish Python configuration",
            "risk": 0.68,
            "verifiable": True,
        },
        {
            "name": "unknown_cold_start",
            "prompt": "General reasoning",
            "registry": unknown_registry,
        },
    ]


__all__ = ["register_runtime_intelligence_commands"]
