"""CLI commands for model and provider profiles.

Commands: model list/show/discover/verify/probe/observations,
          provider list/show, profile stale/verify
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.intelligence.profiles import (
    JsonlProfileStore,
    ModelDiscoveryOrchestrator,
    ProbeFramework,
    StaticConfigDiscovery,
    ProviderRegistryDiscovery,
    build_provisional_profile,
    build_provisional_provider_profile,
    profile_staleness_report,
)

app = typer.Typer(help="Model and provider profile management.")
model_app = typer.Typer(help="Model profile commands.")
provider_app = typer.Typer(help="Provider profile commands.")
profile_app = typer.Typer(help="Profile maintenance commands.")
app.add_typer(model_app, name="model")
app.add_typer(provider_app, name="provider")
app.add_typer(profile_app, name="profile")

WORKSPACE_ROOT = Path(".nous")


def _get_store() -> JsonlProfileStore:
    return JsonlProfileStore(WORKSPACE_ROOT)


# model commands

@model_app.command("list")
def model_list(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List all known model profiles."""
    store = _get_store()
    models = store.list_model_profiles()
    if json_output:
        print(json.dumps([m.to_dict() for m in models], indent=2))
    else:
        for m in models:
            verified = sum(1 for c in m.capability_claims if c.state.value == "verified")
            print(f"{m.model_id:30s} {m.lifecycle.value:12s} {m.provider_family:15s} caps={len(m.capability_claims)} verified={verified}")


@model_app.command("show")
def model_show(
    model_id: str = typer.Argument(..., help="Model ID to show"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show detailed model profile."""
    store = _get_store()
    profile = store.get_model_profile(model_id)
    if profile is None:
        typer.echo(f"Model '{model_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if json_output:
        print(json.dumps(profile.to_dict(), indent=2))
    else:
        print(f"Model:        {profile.model_id}")
        print(f"Display:      {profile.display_name}")
        print(f"Family:       {profile.provider_family}")
        print(f"Lifecycle:    {profile.lifecycle.value}")
        print(f"Hash:         {profile.profile_hash}")
        print(f"Discovered:   {profile.discovered_at}")
        print(f"Updated:      {profile.updated_at}")
        print(f"Source:       {profile.discovery_source}")
        print(f"Context:      {profile.context_window.value} {profile.context_window.unit} (conf={profile.context_window.confidence:.2f})")
        print(f"Streaming:    {profile.supports_streaming.value} (conf={profile.supports_streaming.confidence:.2f})")
        print(f"Tools:        {profile.supports_tool_calling.value} (conf={profile.supports_tool_calling.confidence:.2f})")
        print(f"Structured:   {profile.supports_structured_output.value} (conf={profile.supports_structured_output.confidence:.2f})")
        print(f"Perf samples: {profile.performance.sample_count}")
        if profile.performance.success_rate is not None:
            print(f"Success rate: {profile.performance.success_rate:.2%}")
        if profile.performance.p50_ms is not None:
            print(f"Latency p50:  {profile.performance.p50_ms}ms")
        print("Capabilities:")
        for c in profile.capability_claims:
            print(f"  {c.capability_id:30s} {c.state.value:12s} conf={c.confidence:.2f}")


@model_app.command("discover")
def model_discover(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Discover models from configured sources."""
    orchestrator = ModelDiscoveryOrchestrator([
        StaticConfigDiscovery(),
        ProviderRegistryDiscovery(),
    ])
    records = orchestrator.discover_all()
    store = _get_store()

    for record in records:
        if record.error:
            typer.echo(f"Error [{record.source}]: {record.error}", err=True)
            continue
        store.append_discovery_record(record)

        # Build provisional profile if model was discovered
        if record.model_id:
            profile = build_provisional_profile(record)
            store.save_model_profile(profile)
            if not json_output:
                typer.echo(f"Discovered model: {record.model_id} (source: {record.source})")

        if record.provider_id and not record.model_id:
            pprofile = build_provisional_provider_profile(record)
            store.save_provider_profile(pprofile)
            if not json_output:
                typer.echo(f"Discovered provider: {record.provider_id} (source: {record.source})")

    if json_output:
        print(json.dumps([r.to_dict() for r in records], indent=2))


@model_app.command("verify")
def model_verify(
    model_id: str = typer.Argument(..., help="Model ID to verify"),
) -> None:
    """Mark a model as verified (manual verification)."""
    store = _get_store()
    profile = store.get_model_profile(model_id)
    if profile is None:
        typer.echo(f"Model '{model_id}' not found.", err=True)
        raise typer.Exit(code=1)

    from nous_runtime.intelligence.profiles.models import ModelLifecycle, ModelProfile
    updated = ModelProfile(
        model_id=profile.model_id,
        display_name=profile.display_name,
        provider_family=profile.provider_family,
        lifecycle=ModelLifecycle.VERIFIED,
        context_window=profile.context_window,
        capability_claims=profile.capability_claims,
        pricing=profile.pricing,
        performance=profile.performance,
        discovered_at=profile.discovered_at,
        discovery_source=profile.discovery_source,
        metadata={**profile.metadata, "manually_verified": True},
    )
    store.save_model_profile(updated)
    typer.echo(f"Model '{model_id}' verified.")


@model_app.command("probe")
def model_probe(
    model_id: str = typer.Argument(..., help="Model ID to probe"),
    probe_id: str = typer.Option("", "--probe", help="Specific probe ID (default: all low-risk)"),
    provider_id: str = typer.Option("", "--provider", help="Provider ID"),
    force: bool = typer.Option(False, "--force", help="Force probe even if risk is high"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Run capability probes against a model."""
    framework = ProbeFramework()
    if probe_id:
        result = framework.probe(probe_id, model_id, provider_id, force=force)
        results = [result]
    else:
        results = framework.probe_all(model_id, provider_id, force=force)

    store = _get_store()
    for r in results:
        store.append_probe_result(r)

    if json_output:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for r in results:
            status = "PASS" if r.success else "FAIL"
            detail = r.error or f"{r.latency_ms}ms"
            print(f"  {r.probe_id:25s} {status:5s} {detail}")


@model_app.command("observations")
def model_observations(
    model_id: str = typer.Argument(..., help="Model ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of observations"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show recent performance observations for a model."""
    store = _get_store()
    obs_list = store.list_performance_observations(model_id=model_id, limit=limit)
    if json_output:
        print(json.dumps([o.to_dict() for o in obs_list], indent=2))
    else:
        for o in obs_list:
            status = "OK" if o.success else "FAIL"
            print(f"{o.observed_at}  {status:5s} {o.latency_ms:8.1f}ms  {o.capability_id:20s}  {o.task_type}")


# provider commands

@provider_app.command("list")
def provider_list(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show configured Providers and their Runtime availability."""
    from nous_runtime.cli.provider_experience import (
        configured_provider_rows,
        render_provider_dashboard,
    )

    if json_output:
        rows = []
        for item in configured_provider_rows():
            row = dict(item)
            row["credential"] = item["credential"].__dict__
            rows.append(row)
        print(json.dumps(rows, indent=2))
    else:
        typer.echo(render_provider_dashboard())


@provider_app.command("show")
def provider_show(
    provider_id: str = typer.Argument(..., help="Provider ID to show"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show one configured Provider."""
    from nous_runtime.cli.provider_experience import configured_provider_rows

    item = next(
        (row for row in configured_provider_rows() if row["provider_id"] == provider_id),
        None,
    )
    if item is None:
        typer.echo(f"Provider '{provider_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if json_output:
        data = dict(item)
        data["credential"] = item["credential"].__dict__
        print(json.dumps(data, indent=2))
        return
    typer.echo(f"Provider:       {item['provider_id']}")
    typer.echo(f"Display:        {item['name']}")
    typer.echo(f"Type:           {item['kind']}")
    typer.echo(f"Health:         {item['health']}")
    typer.echo(f"Default model:  {item['model']}")
    typer.echo(f"Context window: {item['context_window']}")
    typer.echo(f"Capabilities:   {', '.join(item['capabilities']) or 'none'}")
    typer.echo(f"Credential:     {item['credential'].source} - {item['credential'].detail}")


@provider_app.command("add")
def provider_add() -> None:
    """Open the interactive Provider Wizard."""
    from nous_runtime.cli.provider_setup import run_provider_setup

    typer.echo(run_provider_setup())


@provider_app.command("quick")
def provider_quick() -> None:
    """Configure a common Provider with process-scoped credentials."""
    from nous_runtime.cli.provider_setup import run_provider_setup

    typer.echo(run_provider_setup(quick=True))


@provider_app.command("health")
def provider_health() -> None:
    """Show configured Provider health without a network probe."""
    from nous_runtime.cli.provider_experience import render_provider_dashboard

    typer.echo(render_provider_dashboard())


@provider_app.command("status")
def provider_status(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show per-Provider model, health, latency, and credential availability."""
    from nous_runtime.cli.provider_experience import (
        configured_provider_rows,
        render_provider_status,
    )

    rows = configured_provider_rows()
    if json_output:
        data = []
        for item in rows:
            row = dict(item)
            row["credential"] = item["credential"].__dict__
            data.append(row)
        print(json.dumps(data, indent=2))
    else:
        typer.echo(render_provider_status(rows))


@provider_app.command("doctor")
def provider_doctor(
    provider_id: str = typer.Argument("", help="Provider ID; omit to diagnose all"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Diagnose Provider configuration, authentication, models, and latency."""
    from nous_runtime.cli.provider_experience import (
        diagnose_provider,
        read_provider_configs,
        render_provider_doctor,
    )

    targets = [provider_id] if provider_id else list(read_provider_configs())
    if not targets:
        typer.echo("No configured Providers. Use 'nous provider add' first.", err=True)
        raise typer.Exit(code=1)
    results = [diagnose_provider(target) for target in targets]
    if json_output:
        print(json.dumps(results[0] if provider_id else results, indent=2))
    else:
        typer.echo("\n\n".join(render_provider_doctor(result) for result in results))
    if any(not result.get("ok") for result in results):
        raise typer.Exit(code=1)


def _provider_probe_command(provider_id: str, operation: str, json_output: bool) -> None:
    from nous_runtime.cli.provider_experience import probe_provider, render_probe_result

    result = probe_provider(provider_id, operation)
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        typer.echo(render_probe_result(result))
    if not result.get("ok"):
        raise typer.Exit(code=1)


@provider_app.command("test")
def provider_test(
    provider_id: str = typer.Argument(..., help="Configured Provider ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Send a minimal model request to a configured Provider."""
    _provider_probe_command(provider_id, "test", json_output)


@provider_app.command("ping")
def provider_ping(
    provider_id: str = typer.Argument(..., help="Configured Provider ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Check endpoint reachability without claiming model correctness."""
    _provider_probe_command(provider_id, "ping", json_output)

# profile maintenance commands

@profile_app.command("stale")
def profile_stale(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List stale profiles."""
    store = _get_store()
    stale = store.find_stale_profiles()
    if json_output:
        reports = [profile_staleness_report(p) for p in stale]
        print(json.dumps(reports, indent=2))
    else:
        if not stale:
            typer.echo("No stale profiles found.")
            return
        for p in stale:
            pid = p.model_id if hasattr(p, 'model_id') else p.provider_id
            lc = p.lifecycle.value if hasattr(p, 'lifecycle') else 'n/a'
            print(f"STALE: {pid:30s} lifecycle={lc}")


@profile_app.command("store")
def profile_store(
    action: str = typer.Argument("rebuild", help="Action: rebuild or verify"),
    verify: bool = typer.Option(False, "--verify", help="Verify profile store integrity"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Profile store maintenance."""
    store = _get_store()
    if action == "verify":
        verify = True
    if action not in {"rebuild", "verify"}:
        typer.echo("Supported actions: rebuild, verify", err=True)
        raise typer.Exit(code=1)
    if verify:
        result = store.verify_integrity()
        if json_output:
            print(json.dumps(result, indent=2))
            return
        if result["ok"]:
            typer.echo("Profile store integrity: OK")
        else:
            typer.echo(f"Profile store integrity: FAILED — {result['invalid_records']} invalid records")
            raise typer.Exit(code=1)
    else:
        idx = store.rebuild_indexes()
        if json_output:
            print(json.dumps(idx, indent=2))
            return
        typer.echo(f"Models: {idx['models']}, Providers: {idx['providers']}")


if __name__ == "__main__":
    app()


# Backward-compatible public names retained for integrations.
list_providers = provider_list
show_provider = provider_show
add_provider = provider_add
