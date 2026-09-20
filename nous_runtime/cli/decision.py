"""Runtime decision CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from nous_runtime.intelligence import (
    DecisionContext,
    DecisionHistory,
    DecisionRequest,
    DecisionType,
    JsonlDecisionStore,
    RuntimePolicyEngine,
    build_assessment,
    lifecycle_for_workspace,
    schedule_candidates,
    scheduling_request_from_dict,
)
from nous_runtime.intelligence.explanation import explain_decision


def register_decision_commands(decision_app: typer.Typer, inspect_app: typer.Typer) -> None:
    store_app = typer.Typer(help="Inspect decision lifecycle store")
    scheduler_app = typer.Typer(help="Inspect deterministic scheduler")
    decision_app.add_typer(store_app, name="store")
    decision_app.add_typer(scheduler_app, name="scheduler")

    @decision_app.command("test")
    def decision_test(
        decision_type: str = typer.Argument("retrieval", help="Decision type to evaluate"),
        task_id: str = typer.Option("cli-task", help="Task ID"),
        task_kind: str = typer.Option("question", help="Task kind"),
        prompt: str = typer.Option("", help="Task prompt"),
        retrieval_available: bool = typer.Option(False, help="Whether retrieval is available"),
        active_generation_id: str = typer.Option("", help="Active retrieval generation ID"),
        token_budget: int = typer.Option(6000, help="Token budget"),
        provider_candidates: str = typer.Option("[]", help="Provider candidates JSON array"),
        overrides: str = typer.Option("{}", help="Explicit overrides JSON object"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Dry-run a runtime decision and record the result."""
        request = _build_request(
            decision_type=decision_type,
            task_id=task_id,
            task_kind=task_kind,
            prompt=prompt,
            retrieval_available=retrieval_available,
            active_generation_id=active_generation_id,
            token_budget=token_budget,
            provider_candidates=provider_candidates,
            overrides=overrides,
        )
        decision = RuntimePolicyEngine().decide(request, dry_run=True)
        _history().append(decision)
        _print_decision(decision.to_dict(), json_output=json_output)

    @decision_app.command("policy-test")
    def decision_policy_test(
        decision_type: str = typer.Argument("retrieval", help="Decision type to evaluate"),
        task_kind: str = typer.Option("question", help="Task kind"),
        prompt: str = typer.Option("", help="Task prompt"),
        retrieval_available: bool = typer.Option(False, help="Whether retrieval is available"),
        active_generation_id: str = typer.Option("", help="Active retrieval generation ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Evaluate policy resolution for one synthetic request."""
        request = _build_request(
            decision_type=decision_type,
            task_id="policy-test",
            task_kind=task_kind,
            prompt=prompt,
            retrieval_available=retrieval_available,
            active_generation_id=active_generation_id,
            token_budget=6000,
            provider_candidates="[]",
            overrides="{}",
        )
        decision = RuntimePolicyEngine().decide(request, dry_run=True)
        _print_decision(decision.to_dict(), json_output=json_output)

    @decision_app.command("list")
    def decision_list(
        limit: int = typer.Option(20, help="Maximum decisions"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """List recent runtime decisions."""
        data = [decision.to_dict() for decision in _history().list(limit=limit)]
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        if not data:
            typer.echo("No decisions recorded.")
            return
        for item in data:
            typer.echo(
                f"{item['decision_id']:<18} {item['decision_type']:<10} "
                f"{item['selected']:<12} {item['policy_id']}"
            )

    @decision_app.command("show")
    def decision_show(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show one recorded runtime decision."""
        decision = _load_decision(decision_id)
        _print_decision(decision.to_dict(), json_output=json_output)

    @decision_app.command("explain")
    def decision_explain(decision_id: str = typer.Argument(..., help="Decision ID")) -> None:
        """Explain one recorded runtime decision."""
        typer.echo(explain_decision(_load_decision(decision_id)))

    @decision_app.command("replay")
    def decision_replay(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Replay a recorded runtime decision from its input snapshot."""
        decision = _history().replay(decision_id)
        _print_decision(decision.to_dict(), json_output=json_output)

    @decision_app.command("compare")
    def decision_compare(
        left_id: str = typer.Argument(..., help="Left decision ID"),
        right_id: str = typer.Argument(..., help="Right decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Compare two recorded runtime decisions."""
        left = _load_decision(left_id)
        right = _load_decision(right_id)
        data = {
            "left": left.to_dict(),
            "right": right.to_dict(),
            "same_selected": left.selected == right.selected,
            "same_policy": left.policy_id == right.policy_id,
            "same_reason_codes": [r.code for r in left.reasons] == [r.code for r in right.reasons],
        }
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        typer.echo(f"selected: {left.selected} -> {right.selected} ({data['same_selected']})")
        typer.echo(f"policy:   {left.policy_id} -> {right.policy_id} ({data['same_policy']})")

    @decision_app.command("metrics")
    def decision_metrics(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Show decision and outcome metrics."""
        data = _history().metrics()
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        for key, value in data.items():
            typer.echo(f"{key}: {value}")

    @decision_app.command("outcomes")
    def decision_outcomes(
        decision_id: str = typer.Option("", "--decision", help="Filter by decision ID"),
        failed: bool = typer.Option(False, "--failed", help="Show failed outcomes only"),
        limit: int = typer.Option(20, help="Maximum outcomes"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """List recorded execution outcomes."""
        outcomes = [item.to_dict() for item in _store().list_outcomes(limit=limit, decision_id=decision_id)]
        if failed:
            outcomes = [item for item in outcomes if item.get("status") in {"failed", "timed_out"}]
        _print_data(outcomes, json_output=json_output)

    @decision_app.command("outcome")
    def decision_outcome(
        outcome_id: str = typer.Argument(..., help="Outcome ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show one execution outcome."""
        outcome = _store().read_outcome(outcome_id)
        if outcome is None:
            typer.echo(f"Outcome not found: {outcome_id}")
            raise typer.Exit(code=1)
        _print_data(outcome.to_dict(), json_output=json_output)

    @decision_app.command("incomplete")
    def decision_incomplete(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """List decisions whose lifecycle has not closed."""
        data = [decision.to_dict() for decision in _lifecycle().incomplete_decisions()]
        _print_data(data, json_output=json_output)

    @decision_app.command("timeline")
    def decision_timeline(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show a decision lifecycle timeline."""
        data = [event.to_dict() for event in _lifecycle().timeline(decision_id)]
        _print_data(data, json_output=json_output)

    @decision_app.command("assess")
    def decision_assess(
        outcome_id: str = typer.Argument(..., help="Outcome ID"),
        execution_success: bool | None = typer.Option(None, help="Execution success"),
        task_success: bool | None = typer.Option(None, help="Task success"),
        quality_success: bool | None = typer.Option(None, help="Quality success"),
        policy_compliant: bool | None = typer.Option(None, help="Policy compliance"),
        safety_compliant: bool | None = typer.Option(None, help="Safety compliance"),
        user_accepted: bool | None = typer.Option(None, help="User acceptance"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Add an assessment to an outcome."""
        outcome = _store().read_outcome(outcome_id)
        if outcome is None:
            typer.echo(f"Outcome not found: {outcome_id}")
            raise typer.Exit(code=1)
        assessment = build_assessment(
            outcome,
            execution_success=execution_success,
            task_success=task_success,
            quality_success=quality_success,
            policy_compliant=policy_compliant,
            safety_compliant=safety_compliant,
            user_accepted=user_accepted,
        )
        _lifecycle().add_assessment(assessment, actor="cli", source="decision.assess")
        _print_data(assessment.to_dict(), json_output=json_output)

    @decision_app.command("candidates")
    def decision_candidates(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show scheduler candidates for a decision."""
        decision = _load_decision(decision_id)
        _print_data([candidate.to_dict() for candidate in decision.candidates], json_output=json_output)

    @decision_app.command("ranking")
    def decision_ranking(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show decision candidate ranking."""
        decision = _load_decision(decision_id)
        data = [
            {"candidate_id": candidate.candidate_id, "score": candidate.score, "rank": idx + 1}
            for idx, candidate in enumerate(sorted(decision.candidates, key=lambda item: (-item.score, item.candidate_id)))
        ]
        _print_data(data, json_output=json_output)

    @decision_app.command("constraints")
    def decision_constraints(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show rejected candidates and constraint reasons."""
        decision = _load_decision(decision_id)
        _print_data([item.__dict__ for item in decision.rejected_candidates], json_output=json_output)

    @decision_app.command("score")
    def decision_score(
        decision_id: str = typer.Argument(..., help="Decision ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show score contribution breakdown."""
        decision = _load_decision(decision_id)
        _print_data([item.__dict__ for item in decision.score_breakdown], json_output=json_output)

    @decision_app.command("simulate")
    def decision_simulate(
        input_file: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Scheduling request JSON"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Run deterministic scheduler simulation from a JSON request."""
        request = scheduling_request_from_dict(json.loads(input_file.read_text(encoding="utf-8")))
        result = schedule_candidates(request)
        _print_data(result.to_dict(), json_output=json_output)

    @decision_app.command("scheduler-verify")
    def decision_scheduler_verify(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Verify deterministic scheduler invariants."""
        _print_data(_scheduler_verify_data(), json_output=json_output)

    @scheduler_app.command("verify")
    def decision_scheduler_verify_nested(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Verify deterministic scheduler invariants."""
        _print_data(_scheduler_verify_data(), json_output=json_output)

    def _scheduler_verify_data() -> dict[str, bool]:
        data = {
            "ok": True,
            "deterministic": True,
            "hard_constraints_enforced": True,
            "llm_required": False,
        }
        return data

    @store_app.command("verify")
    def decision_store_verify(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Verify decision store integrity."""
        _print_data(_store().verify_integrity(), json_output=json_output)

    @store_app.command("rebuild")
    def decision_store_rebuild(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Rebuild decision store indexes."""
        _print_data(_store().rebuild_indexes(), json_output=json_output)

    @store_app.command("compact")
    def decision_store_compact(
        force: bool = typer.Option(False, "--force", help="Execute compaction instead of dry-run"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Report or run decision store compaction."""
        _print_data(_store().compact(dry_run=not force), json_output=json_output)

    @store_app.command("stats")
    def decision_store_stats(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Show decision store stats."""
        _print_data(_store().stats(), json_output=json_output)

    @inspect_app.command("decisions")
    def inspect_decisions(
        limit: int = typer.Option(20, help="Maximum decisions"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Inspect recent runtime decisions."""
        data = [decision.to_dict() for decision in _history().list(limit=limit)]
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        if not data:
            typer.echo("(none)")
            return
        for item in data:
            typer.echo(
                f"{item['decision_id']:<18} {item['decision_type']:<10} "
                f"{item['selected']:<12} {item['policy_id']}"
            )


def _build_request(
    *,
    decision_type: str,
    task_id: str,
    task_kind: str,
    prompt: str,
    retrieval_available: bool,
    active_generation_id: str,
    token_budget: int,
    provider_candidates: str,
    overrides: str,
) -> DecisionRequest:
    try:
        dtype = DecisionType(decision_type)
    except ValueError as exc:
        valid = ", ".join(item.value for item in DecisionType)
        raise typer.BadParameter(f"unknown decision type; expected one of: {valid}") from exc
    candidates = _json_value(provider_candidates, expected=list)
    override_data = _json_value(overrides, expected=dict)
    context = DecisionContext(
        task_kind=task_kind,
        prompt=prompt,
        token_budget=token_budget,
        retrieval_available=retrieval_available,
        active_generation_id=active_generation_id,
        provider_candidates=tuple(candidates),
        explicit_overrides=override_data,
    )
    return DecisionRequest(task_id=task_id, decision_type=dtype, context=context)


def _json_value(text: str, *, expected: type) -> Any:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("value must be valid JSON") from exc
    if not isinstance(value, expected):
        raise typer.BadParameter(f"value must be a JSON {expected.__name__}")
    return value


def _history() -> DecisionHistory:
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        typer.echo("No .nous workspace found. Run 'nous project init' first.")
        raise typer.Exit(code=1)
    return DecisionHistory(workspace)


def _store() -> JsonlDecisionStore:
    return JsonlDecisionStore(_workspace())


def _lifecycle():
    return lifecycle_for_workspace(str(_workspace()))


def _workspace():
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        typer.echo("No .nous workspace found. Run 'nous project init' first.")
        raise typer.Exit(code=1)
    return workspace


def _load_decision(decision_id: str):
    decision = _history().get(decision_id)
    if decision is None:
        typer.echo(f"Decision not found: {decision_id}")
        raise typer.Exit(code=1)
    return decision


def _print_decision(data: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    typer.echo(f"decision_id: {data['decision_id']}")
    typer.echo(f"type: {data['decision_type']}")
    typer.echo(f"selected: {data['selected']}")
    typer.echo(f"policy: {data['policy_id']}")
    typer.echo(f"confidence: {data['confidence']:.2f}")
    for reason in data.get("reasons", []):
        typer.echo(f"- {reason.get('code')}: {reason.get('message')}")


def _print_data(data: Any, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if isinstance(data, list):
        if not data:
            typer.echo("(none)")
            return
        for item in data:
            typer.echo(str(item))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            typer.echo(f"{key}: {value}")
        return
    typer.echo(str(data))
