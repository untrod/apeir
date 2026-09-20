"""Runtime policy CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from nous_runtime.intelligence import DecisionContext, DecisionRequest, DecisionType, RuntimePolicyEngine
from nous_runtime.intelligence.policy_loader import (
    PolicyLoadResult,
    load_workspace_policies,
    parse_policy_spec,
    stable_policy_hash,
    validate_policy_spec,
)


def register_policy_commands(policy_app: typer.Typer) -> None:
    @policy_app.command("list")
    def policy_list(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """List workspace policies."""
        loaded = _loaded()
        data = loaded.to_dict()
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        if not loaded.specs:
            typer.echo("No workspace policies.")
        for spec in loaded.specs:
            typer.echo(f"{spec.policy_id:<32} {spec.decision_type:<12} {spec.source:<18} {spec.policy_hash}")
        for diagnostic in loaded.diagnostics:
            typer.echo(f"{diagnostic.severity}: {diagnostic.code} {diagnostic.source_path} {diagnostic.message}")

    @policy_app.command("show")
    def policy_show(
        policy_id: str = typer.Argument(..., help="Policy ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Show one workspace policy."""
        spec = _find_policy(policy_id)
        data = spec.to_dict()
        if json_output:
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        for key, value in data.items():
            typer.echo(f"{key}: {value}")

    @policy_app.command("validate")
    def policy_validate(
        path: str = typer.Argument("", help="Optional policy file path"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Validate a policy file or the workspace policy directory."""
        if path:
            data = _load_policy_file(Path(path))
            specs = data if isinstance(data, list) else data.get("policies", [data]) if isinstance(data, dict) else []
            diagnostics = []
            for item in specs:
                try:
                    validate_policy_spec(parse_policy_spec(dict(item), source_path=path))
                except Exception as exc:
                    diagnostics.append({"code": "POLICY_INVALID", "message": str(exc), "source_path": path})
            _print_validation(diagnostics, json_output=json_output)
            if diagnostics:
                raise typer.Exit(code=1)
            return
        loaded = _loaded()
        diagnostics = [diag.to_dict() for diag in loaded.diagnostics]
        _print_validation(diagnostics, json_output=json_output)
        if any(item["severity"] == "error" for item in diagnostics):
            raise typer.Exit(code=1)

    @policy_app.command("resolve")
    def policy_resolve(
        decision_type: str = typer.Argument(..., help="Decision type"),
        task_kind: str = typer.Option("question", help="Task kind"),
        prompt: str = typer.Option("", help="Task prompt"),
        retrieval_available: bool = typer.Option(False, help="Whether retrieval is available"),
        active_generation_id: str = typer.Option("", help="Active retrieval generation ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Resolve policies for a synthetic decision request."""
        request = _request(decision_type, task_kind, prompt, retrieval_available, active_generation_id)
        matches = _engine().registry.resolve(request)
        data = [
            {
                "policy_id": policy.policy_id,
                "decision_type": policy.decision_type,
                "priority": policy.priority,
                "metadata": _engine().registry.metadata_for(policy.policy_id),
            }
            for policy in matches
        ]
        _print_data(data, json_output=json_output)

    @policy_app.command("explain")
    def policy_explain(
        policy_id: str = typer.Argument(..., help="Policy ID"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Explain a policy definition."""
        spec = _find_policy(policy_id)
        data = {
            "policy_id": spec.policy_id,
            "policy_type": spec.policy_type,
            "decision_type": spec.decision_type,
            "source": spec.source,
            "priority": spec.priority,
            "effective_priority": _effective_priority_text(spec.source, spec.priority),
            "conditions": list(spec.conditions),
            "actions": spec.actions,
            "policy_hash": spec.policy_hash,
        }
        _print_data(data, json_output=json_output)

    @policy_app.command("test")
    def policy_test(
        policy_id: str = typer.Argument(..., help="Policy ID"),
        input_json: str = typer.Option("{}", "--input", help="Decision input JSON"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Test one policy against a JSON input."""
        spec = _find_policy(policy_id)
        payload = json.loads(input_json)
        context = DecisionContext(**dict(payload.get("context") or {}))
        request = DecisionRequest(
            task_id=str(payload.get("task_id") or "policy-test"),
            decision_type=DecisionType(str(payload.get("decision_type") or spec.decision_type)),
            context=context,
        )
        policy = spec.to_policy()
        data = {
            "matched": policy.matches(request),
            "decision": policy.decide(request).to_dict() if policy.matches(request) else None,
        }
        _print_data(data, json_output=json_output)

    @policy_app.command("diff")
    def policy_diff(
        old: str = typer.Argument(..., help="Old policy file"),
        new: str = typer.Argument(..., help="New policy file"),
        json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
    ) -> None:
        """Compare two policy files by normalized hash."""
        old_data = _load_policy_file(Path(old))
        new_data = _load_policy_file(Path(new))
        data = {
            "old_hash": stable_policy_hash(old_data if isinstance(old_data, dict) else {"policies": old_data}),
            "new_hash": stable_policy_hash(new_data if isinstance(new_data, dict) else {"policies": new_data}),
            "changed": old_data != new_data,
        }
        _print_data(data, json_output=json_output)

    @policy_app.command("reload")
    def policy_reload(json_output: bool = typer.Option(False, "--json", help="Print JSON output")) -> None:
        """Validate and load workspace policies into a fresh registry snapshot."""
        loaded = _loaded()
        data = {
            "policies": len(loaded.specs),
            "diagnostics": [diag.to_dict() for diag in loaded.diagnostics],
        }
        _print_data(data, json_output=json_output)


def _workspace():
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        typer.echo("No .nous workspace found. Run 'nous project init' first.")
        raise typer.Exit(code=1)
    return workspace


def _loaded() -> PolicyLoadResult:
    return load_workspace_policies(_workspace())


def _engine() -> RuntimePolicyEngine:
    return RuntimePolicyEngine.from_workspace(str(_workspace()))


def _find_policy(policy_id: str):
    for spec in _loaded().specs:
        if spec.policy_id == policy_id:
            return spec
    typer.echo(f"Policy not found: {policy_id}")
    raise typer.Exit(code=1)


def _request(
    decision_type: str,
    task_kind: str,
    prompt: str,
    retrieval_available: bool,
    active_generation_id: str,
) -> DecisionRequest:
    return DecisionRequest(
        task_id="policy-resolve",
        decision_type=DecisionType(decision_type),
        context=DecisionContext(
            task_kind=task_kind,
            prompt=prompt,
            retrieval_available=retrieval_available,
            active_generation_id=active_generation_id,
        ),
    )


def _load_policy_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text) or {}


def _print_validation(diagnostics: list[dict[str, Any]], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps({"valid": not diagnostics, "diagnostics": diagnostics}, indent=2, ensure_ascii=False))
        return
    if not diagnostics:
        typer.echo("Policy validation passed.")
        return
    for item in diagnostics:
        typer.echo(f"{item.get('code')}: {item.get('message')}")


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


def _effective_priority_text(source: str, priority: int) -> str:
    from nous_runtime.intelligence.policy_loader import POLICY_SOURCE_ORDER

    return str(POLICY_SOURCE_ORDER[source] * 10_000 + priority)
