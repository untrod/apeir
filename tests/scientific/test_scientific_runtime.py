from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from nous_runtime.api import routes
from nous_runtime.artifact import ArtifactManager, ArtifactRegistry, ArtifactType
from nous_runtime.events import EventStream
from nous_runtime.evidence.service import ResearchEvidenceService
from nous_runtime.scientific import (
    ScientificAnalysisSpec,
    ScientificRuntime,
    ScientificValidationError,
)
from nous_runtime.scientific.providers import provider_inventory
from nous_runtime.simulations import SimulationRuntime
from nous_runtime.kernel.windows_sandbox import executable_path


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


def _simulation_spec():
    return {
        "model_ref": "spacecraft-thermal/v1",
        "initial_state": {"initial_temperature": 290.0},
        "boundary_conditions": {"external_temperature": 3.0},
        "parameters": {
            "solar_flux": 1361.0,
            "surface_area": 2.0,
            "emissivity": 0.8,
            "thermal_capacity": 10000.0,
            "absorptivity": 0.7,
            "max_safe_temperature": 373.15,
        },
        "solver": "explicit-euler",
        "time_step": 1.0,
        "duration": 30.0,
        "seed": 42,
        "network_policy": {"mode": "none"},
        "parameter_space": {"solar_flux": [1000.0, 1361.0]},
        "resource_budget": {
            "cpu_limit": 1.0,
            "memory_limit_mb": 256,
            "wall_time_seconds": 60,
            "max_cases": 8,
            "max_retries": 0,
            "max_output_bytes": 2_000_000,
        },
    }


def _completed_simulation(workspace):
    runtime = SimulationRuntime(workspace)
    created = runtime.create(_simulation_spec())
    return runtime.run(created["simulation_id"])


def test_scientific_contract_is_strict_and_all_providers_are_qualified():
    spec = ScientificAnalysisSpec.from_mapping(
        {
            "simulation_run_id": "simrun_" + "a" * 32,
            "report_formats": ["docx", "pdf"],
            "reference_tolerance_kelvin": 0.05,
        },
        new_identity=True,
    )
    assert spec.schema_version == "nous.scientific-analysis/v1"
    assert spec.reference_solver == "scipy.solve_ivp"
    assert spec.digest() == ScientificAnalysisSpec.from_mapping(spec.to_dict()).digest()
    inventory = provider_inventory()
    assert set(inventory) == {"numpy", "scipy", "pandas", "sympy", "matplotlib"}
    assert all(item["available"] and item["version"] for item in inventory.values())

    with pytest.raises(ScientificValidationError, match="unknown scientific"):
        ScientificAnalysisSpec.from_mapping(
            {"simulation_run_id": "simrun_" + "a" * 32, "host_shell": True},
            new_identity=True,
        )
    with pytest.raises(ScientificValidationError, match="between"):
        ScientificAnalysisSpec.from_mapping(
            {
                "simulation_run_id": "simrun_" + "a" * 32,
                "reference_tolerance_kelvin": 100,
            },
            new_identity=True,
        )


def test_artifact_only_evidence_is_validated_and_traceable(tmp_path):
    manager = ArtifactManager(ArtifactRegistry(tmp_path / ".nous" / "artifacts.jsonl"))
    output = tmp_path / "analysis.json"
    output.write_text("{}\n", encoding="utf-8")
    artifact = manager.create(
        ArtifactType.REPORT,
        "Scientific analysis",
        location="analysis.json",
        metadata={"sha256": hashlib.sha256(output.read_bytes()).hexdigest()},
    )
    service = ResearchEvidenceService(tmp_path)
    detail = service.create_claim(
        {
            "statement": "The local scientific result is supported.",
            "evidence": [
                {
                    "artifact_ref": artifact.id,
                    "relation": "supports",
                    "strength": 1.0,
                }
            ],
        }
    )
    assert detail["claim"]["verification_state"] == "supported"
    assert detail["trace_complete"] is True
    assert detail["artifact_refs"] == [artifact.id]


@requires_strong_sandbox
def test_scientific_runtime_closes_simulation_claim_document_loop(tmp_path):
    simulation_run = _completed_simulation(tmp_path)
    runtime = ScientificRuntime(tmp_path)
    result = runtime.analyze(
        {
            "simulation_run_id": simulation_run["simulation_run_id"],
            "report_formats": ["docx", "pdf"],
            "reference_tolerance_kelvin": 0.05,
        }
    )

    assert result["state"] == "completed"
    assert result["case_count"] == 2
    assert result["reference_verified"] is True
    assert result["maximum_reference_error_kelvin"] < 0.05
    assert result["environment_state"] == "destroyed"
    assert {item["name"] for item in result["artifacts"]} == {
        "analysis.json",
        "thermal-analysis.csv",
        "thermal-analysis.png",
    }
    for artifact in result["artifacts"]:
        content = (tmp_path / artifact["location"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
    assert len(result["claims"]) == 2
    assert all(
        item["claim"]["verification_state"] == "supported" for item in result["claims"]
    )
    assert all(item["trace_complete"] for item in result["claims"])
    assert result["document"]["verified"] is True
    assert {item["format"] for item in result["document"]["outputs"]} == {"docx", "pdf"}
    for output in result["document"]["outputs"]:
        assert (tmp_path / output["location"]).is_file()

    events = EventStream(str(tmp_path)).load_events(result["event_run_id"])
    event_types = [event.event_type for event in events]
    assert event_types[:4] == [
        "run.created",
        "command.proposed",
        "run.started",
        "scientific.started",
    ]
    assert "scientific.reference_verified" in event_types
    assert "scientific.claims_created" in event_types
    assert "scientific.report_rendered" in event_types
    assert event_types[-2:] == ["scientific.completed", "run.completed"]

    record_path = tmp_path / ".nous" / "scientific" / f"{result['analysis_id']}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["reference_verified"] = False
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ScientificValidationError, match="digest mismatch"):
        runtime.get(result["analysis_id"])


@requires_strong_sandbox
def test_tampered_simulation_artifact_fails_before_scientific_execution(tmp_path):
    simulation_run = _completed_simulation(tmp_path)
    series = next(
        item for item in simulation_run["artifacts"] if item["name"] == "series.csv"
    )
    (tmp_path / series["location"]).write_text(
        "case_id,time,temperature\n", encoding="utf-8"
    )
    with pytest.raises(ScientificValidationError, match="digest mismatch"):
        ScientificRuntime(tmp_path).analyze(
            {"simulation_run_id": simulation_run["simulation_run_id"]}
        )
    assert not list((tmp_path / ".nous" / "scientific").glob("analysis_*.json"))


def test_scientific_route_is_governed_before_handler(monkeypatch, tmp_path):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            return SimpleNamespace(
                action_mode="ASK_APPROVAL",
                rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED",
                reason_message="Approval required",
                decision_id="decision-scientific",
            )

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())

    response = routes.route_server(
        "POST",
        "/api/v1/scientific/analyses",
        body={"simulation_run_id": "simrun_" + "a" * 32},
        auth={"token": "secret", "loopback": True},
    )
    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    proposal = captured["proposal"]
    assert proposal.capability_id == "scientific.analyze"
    assert proposal.required_permissions == ("runtime.execute", "scientific.compute")
    assert not (tmp_path / ".nous" / "scientific").exists()


def test_scientific_worker_cli_is_registered(monkeypatch):
    from nous_runtime.cli.main import app

    captured = {}

    def fake_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr("nous_runtime.scientific.worker.main", fake_main)
    result = CliRunner().invoke(
        app,
        ["scientific-worker", "--input", "input.json", "--output-dir", "outputs"],
    )
    assert result.exit_code == 0
    assert captured["args"] == ["--input", "input.json", "--output-dir", "outputs"]
