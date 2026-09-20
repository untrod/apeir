import json

from typer.testing import CliRunner

from nous_runtime.api.routes import route
from nous_runtime.capability.resolver import execute_capability_observation
from nous_runtime.cli.main import app
from nous_runtime.intelligence.consistency import verify_cross_store_consistency
from nous_runtime.intelligence.profiles import JsonlProfileStore
from nous_runtime.intelligence.reliability import (
    CircuitState,
    FallbackBoundary,
    FallbackCompatibility,
    JsonlReliabilityStore,
    assess_fallback_safety,
)
from nous_runtime.intelligence.reliability.models import CircuitStateRecord, snapshot_hash
from nous_runtime.project.workspace import init_workspace
from remote_terminal.nous_core import provider as provider_registry
from remote_terminal.nous_core.provider import Provider, invoke_via_provider_observation, register_adapter, unregister_adapter


CAPABILITY_ID = "test.p572.reason"


class _Provider(Provider):
    def __init__(self, provider_id: str, results):
        self.provider_id = provider_id
        self.provider_name = provider_id
        self.results = list(results)
        self.calls = 0

    def list_capabilities(self):
        return [CAPABILITY_ID]

    def invoke(self, capability_id, **params):
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "content": "ok", "model": params.get("model", "m")}

    def health(self):
        return {"status": "ok"}


def _workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return init_workspace(tmp_path)


def _install(*providers):
    for provider_id in list(provider_registry._providers):
        if str(provider_id).startswith("p572_"):
            unregister_adapter(provider_id)
    for provider in providers:
        unregister_adapter(provider.provider_id)
        register_adapter(provider)
    return providers


def test_primary_cli_profile_registration_clean_workspace(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    runner = CliRunner()

    commands = [
        ["model", "list", "--json"],
        ["model", "discover", "--json"],
        ["provider", "list", "--json"],
        ["profile", "stale", "--json"],
        ["profile", "store", "verify", "--json"],
    ]

    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.stdout
        json.loads(result.stdout)


def test_legacy_provider_path_routes_through_reliability(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    (provider,) = _install(_Provider("p572_legacy", [{"ok": True, "content": "legacy", "model": "m"}]))

    obs = invoke_via_provider_observation(provider.provider_id, CAPABILITY_ID, {"model": "m"})
    store = JsonlReliabilityStore(ws)

    assert obs.status == "success"
    assert obs.metadata["reliability_wrapped"] is True
    assert obs.metadata["deprecated_path"] is True
    assert store.get_current_health(provider.provider_id, "m") is not None


def test_equivalent_fallback_executes_and_records(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    primary, fallback = _install(
        _Provider("p572_primary", [{"ok": False, "error": "server_error", "http_status": 500}]),
        _Provider("p572_fallback", [{"ok": True, "content": "fallback", "model": "m"}]),
    )

    obs = execute_capability_observation(
        CAPABILITY_ID,
        prompt="hello",
        model="m",
        _max_attempts=1,
        _fallback_boundary={
            "modality": "text",
            "privacy_level": "local",
            "locality": "same",
            "output_guarantees": ["text"],
            "permissions": ["model"],
            "side_effects": [],
            "risk_level": "low",
            "cost_budget": 1.0,
            "latency_budget_ms": 5000,
            "max_depth": 2,
        },
        _fallback_candidates=[
            {
                "provider_id": fallback.provider_id,
                "model_id": "m",
                "capability_id": CAPABILITY_ID,
                "modality": "text",
                "privacy_level": "local",
                "locality": "same",
                "output_guarantees": ["text"],
                "permissions": ["model"],
                "side_effects": [],
                "risk_level": "low",
                "estimated_cost": 0.1,
                "estimated_latency_ms": 100,
                "profile_confidence": 0.9,
            }
        ],
    )
    store = JsonlReliabilityStore(ws)

    assert obs.status == "success"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert store.list_fallbacks()


def test_fallback_rejects_privacy_locality_capability_and_unknown():
    boundary = FallbackBoundary(
        capability_id=CAPABILITY_ID,
        modality="text",
        privacy_level="local",
        locality="same",
        output_guarantees=("text",),
        permissions=("model",),
        risk_level="low",
    )

    assert not assess_fallback_safety(boundary, FallbackCompatibility("p", capability_id=CAPABILITY_ID, modality="text", privacy_level="cloud", locality="same", output_guarantees=("text",), permissions=("model",), risk_level="low", profile_confidence=1.0)).allowed
    assert not assess_fallback_safety(boundary, FallbackCompatibility("p", capability_id=CAPABILITY_ID, modality="text", privacy_level="local", locality="other", output_guarantees=("text",), permissions=("model",), risk_level="low", profile_confidence=1.0)).allowed
    assert not assess_fallback_safety(boundary, FallbackCompatibility("p", capability_id="other.capability", modality="text", privacy_level="local", locality="same", output_guarantees=("text",), permissions=("model",), risk_level="low", profile_confidence=1.0)).allowed
    assert not assess_fallback_safety(boundary, FallbackCompatibility("p", capability_id=CAPABILITY_ID)).allowed


def test_fallback_loop_depth_and_circuit_rejections():
    boundary = FallbackBoundary(capability_id=CAPABILITY_ID, max_depth=1)
    candidate = FallbackCompatibility("p", capability_id=CAPABILITY_ID, profile_confidence=1.0)

    assert assess_fallback_safety(boundary, candidate, depth=1).reason_code == "FALLBACK_DEPTH_LIMIT"
    assert assess_fallback_safety(boundary, candidate, visited=("p",)).reason_code == "FALLBACK_LOOP"
    blocked = FallbackCompatibility("p2", capability_id=CAPABILITY_ID, profile_confidence=1.0, circuit_state=CircuitState.FORCED_OPEN.value)
    assert assess_fallback_safety(boundary, blocked).reason_code == "CIRCUIT_BLOCKED"


def test_profile_observations_failed_attempts_and_idempotency(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    (provider,) = _install(_Provider("p572_obs", [{"ok": False, "error": "server_error", "http_status": 500}]))

    execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m", _max_attempts=1)
    execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m", _max_attempts=1)
    observations = JsonlProfileStore(ws).list_performance_observations(model_id="m", limit=100)
    rebuilt = JsonlProfileStore(ws).rebuild_indexes()

    assert observations
    assert any(not obs.success for obs in observations)
    assert len({obs.observation_id for obs in observations}) == len(observations)
    assert rebuilt["performance_observations"] == len(observations)
    assert provider.calls == 2


def test_cross_store_and_inspector_reliability_closure(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    (provider,) = _install(_Provider("p572_cross", [{"ok": True, "content": "ok", "model": "m"}]))

    obs = execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m")
    consistency = verify_cross_store_consistency(ws)
    api = route("GET", "/api/inspector/providers/reliability", params={"provider_id": provider.provider_id})
    global_api = route("GET", "/api/inspector/providers/reliability")

    assert obs.status == "success"
    assert consistency["ok"] is True
    assert api["ok"] is True
    assert api["data"]["profile_observations"]
    assert global_api["data"]["frozen_replay"]


def test_circuit_state_change_during_fallback_blocks_candidate(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    primary, fallback = _install(
        _Provider("p572_circuit_primary", [{"ok": False, "error": "server_error", "http_status": 500}]),
        _Provider("p572_circuit_fallback", [{"ok": True, "content": "blocked", "model": "m"}]),
    )
    JsonlReliabilityStore(ws).append_circuit_event(
        CircuitStateRecord(
            record_id=snapshot_hash({"provider": fallback.provider_id, "state": "forced_open"}),
            breaker_key=f"{fallback.provider_id}:*",
            state=CircuitState.FORCED_OPEN,
            transition_reason="test",
        )
    )

    obs = execute_capability_observation(
        CAPABILITY_ID,
        prompt="hello",
        model="m",
        _max_attempts=1,
        _fallback_boundary={"max_depth": 2},
        _fallback_candidates=[{"provider_id": fallback.provider_id, "capability_id": CAPABILITY_ID, "profile_confidence": 1.0, "circuit_state": "forced_open"}],
    )

    assert obs.status == "failed"
    assert primary.calls == 1
    assert fallback.calls == 0
