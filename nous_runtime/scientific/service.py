"""Governed P20 Scientific Runtime and reference-report orchestration."""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.artifact import ArtifactManager, ArtifactRegistry, ArtifactType
from nous_runtime.documents import DocumentRuntime
from nous_runtime.environments import EnvironmentRuntime
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.evidence.service import ResearchEvidenceService
from nous_runtime.locking import file_lock
from nous_runtime.scientific.models import (
    ScientificAnalysisSpec,
    ScientificValidationError,
)
from nous_runtime.schema_registry import SCIENTIFIC_RESULT_SCHEMA_VERSION
from nous_runtime.simulations import SimulationRuntime

_OUTPUT_NAMES = ("analysis.json", "thermal-analysis.csv", "thermal-analysis.png")


class ScientificNotFoundError(ScientificValidationError):
    """Requested scientific analysis does not exist."""


class ScientificRuntime:
    """Scientific Capability Layer over existing Runtime authorities."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise ScientificValidationError("the active workspace does not exist")
        self.storage = self.root / ".nous" / "scientific"
        self.outputs = self.root / "artifacts" / "scientific"
        self.storage.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.events = EventStream(str(self.root))
        self.artifacts = ArtifactManager(
            ArtifactRegistry(self.root / ".nous" / "artifacts.jsonl")
        )
        self.simulations = SimulationRuntime(self.root)
        self.environments = EnvironmentRuntime(self.root)
        self.research = ResearchEvidenceService(self.root)
        self.documents = DocumentRuntime(self.root)

    def status(self) -> dict[str, Any]:
        from nous_runtime.scientific.providers import provider_inventory

        analyses = self.list_analyses()
        return {
            "schema_version": "nous.scientific-runtime/v1",
            "analysis_contract": "nous.scientific-analysis/v1",
            "result_contract": SCIENTIFIC_RESULT_SCHEMA_VERSION,
            "workspace": str(self.root),
            "analyses": len(analyses),
            "completed": sum(item.get("state") == "completed" for item in analyses),
            "failed": sum(item.get("state") == "failed" for item in analyses),
            "providers": provider_inventory(),
            "reference_tasks": [
                {
                    "analysis_type": "spacecraft-thermal-analysis/v1",
                    "simulation_model": "spacecraft-thermal/v1",
                    "outputs": ["json", "csv", "png", "claim-evidence", "docx", "pdf"],
                    "execution_authority": "EnvironmentRuntime",
                }
            ],
            "event_authority": "EventStream",
            "artifact_authority": "ArtifactRegistry",
            "claim_authority": "ClaimEvidenceGraph",
            "document_authority": "DocumentRuntime",
            "defaults": {
                "network": "none",
                "reference_solver": "scipy.solve_ivp:DOP853",
                "reference_tolerance_kelvin": 0.05,
            },
            "evidence_level": "integrated-host",
        }

    def analyze(self, value: Mapping[str, Any]) -> dict[str, Any]:
        spec = ScientificAnalysisSpec.from_mapping(value, new_identity=True)
        simulation_run = self.simulations.get_run(spec.simulation_run_id)
        if simulation_run.get("state") != "completed":
            raise ScientificValidationError(
                "scientific analysis requires a completed Simulation run"
            )
        if simulation_run.get("model_ref") != "spacecraft-thermal/v1":
            raise ScientificValidationError(
                "scientific analysis requires spacecraft-thermal/v1"
            )
        simulation = self.simulations.get(str(simulation_run["simulation_id"]))
        result_artifact = self._simulation_artifact(simulation_run, "result.json")
        series_artifact = self._simulation_artifact(simulation_run, "series.csv")
        result_bytes = self._verified_artifact_bytes(result_artifact)
        series_bytes = self._verified_artifact_bytes(series_artifact)
        event_run_id = f"scientific-analysis-{uuid4().hex}"
        task_id = spec.task_id or f"scientific.analyze:{spec.analysis_id}"
        started_at = _utc_now()
        metadata = {
            "analysis_id": spec.analysis_id,
            "analysis_type": spec.analysis_type,
            "simulation_run_id": spec.simulation_run_id,
            "spec_sha256": spec.digest(),
        }
        self._start(event_run_id, task_id, metadata)
        self._emit(event_run_id, task_id, "scientific.started", metadata)
        environment_id = ""
        execution: dict[str, Any] = {}
        try:
            environment_id = str(
                self._create_environment(spec, event_run_id)["environment_id"]
            )
            payload = {
                **spec.to_dict(),
                "sha256": spec.digest(),
                "simulation": {
                    key: item
                    for key, item in simulation.items()
                    if key not in {"artifact_id", "operation_run_id"}
                },
                "simulation_result_sha256": result_artifact["sha256"],
                "simulation_series_sha256": series_artifact["sha256"],
            }
            self.environments.stage_file(
                environment_id,
                "scientific-input.json",
                (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                ).encode("utf-8"),
            )
            self.environments.stage_file(
                environment_id, "simulation-result.json", result_bytes
            )
            self.environments.stage_file(environment_id, "series.csv", series_bytes)
            if not getattr(sys, "frozen", False):
                _stage_worker_bundle(self.environments, environment_id)
            execution = self.environments.run(
                environment_id,
                {
                    "argv": _worker_argv(),
                    "cwd": ".",
                    "timeout_seconds": 300,
                    "max_output_bytes": 2_000_000,
                },
            )
            if not execution.get("ok"):
                detail = str(execution.get("stderr") or execution.get("stdout") or "")
                raise ScientificValidationError(
                    f"scientific worker failed: {detail[-2048:]}"
                )
            collected = {
                name: self.environments.read_file(
                    environment_id, f"outputs/{name}", max_bytes=20_000_000
                )
                for name in _OUTPUT_NAMES
            }
            self._release_environment(environment_id)
            analysis = json.loads(collected["analysis.json"])
            if analysis.get("analysis_id") != spec.analysis_id:
                raise ScientificValidationError(
                    "scientific worker result identity mismatch"
                )
            if not analysis.get("reference_verified"):
                raise ScientificValidationError(
                    "scientific reference verification exceeded tolerance"
                )
            published = [
                self._publish(spec, event_run_id, task_id, name, collected[name])
                for name in _OUTPUT_NAMES
            ]
            analysis_artifact = next(
                item for item in published if item["name"] == "analysis.json"
            )
            maximum_error = max(
                float(item["maximum_reference_error_kelvin"])
                for item in analysis["cases"]
            )
            self._emit(
                event_run_id,
                task_id,
                "scientific.reference_verified",
                {
                    "analysis_id": spec.analysis_id,
                    "case_count": analysis["case_count"],
                    "reference_tolerance_kelvin": spec.reference_tolerance_kelvin,
                    "maximum_reference_error_kelvin": maximum_error,
                },
            )
            claims = self._create_claims(
                spec,
                analysis,
                analysis_artifact["artifact_id"],
                str(result_artifact["artifact_id"]),
                event_run_id,
                task_id,
            )
            document = self._create_report(
                spec,
                simulation,
                simulation_run,
                analysis,
                claims,
                published,
                event_run_id,
                task_id,
            )
            record = {
                "schema_version": SCIENTIFIC_RESULT_SCHEMA_VERSION,
                **spec.to_dict(),
                "spec_sha256": spec.digest(),
                "state": "completed",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "simulation_id": simulation_run["simulation_id"],
                "event_run_id": event_run_id,
                "environment_id": environment_id,
                "environment_state": self.environments.get(environment_id)["state"],
                "execution_run_id": str(execution.get("operation_run_id") or ""),
                "execution_artifact_id": str(execution.get("artifact_id") or ""),
                "worker_code_hash": _worker_code_hash(),
                "provider_inventory": analysis["provider_inventory"],
                "reference_verified": True,
                "maximum_reference_error_kelvin": maximum_error,
                "safe_during_simulated_duration": bool(
                    analysis["safe_during_simulated_duration"]
                ),
                "case_count": int(analysis["case_count"]),
                "cases": analysis["cases"],
                "equation": analysis["equation"],
                "equilibrium_expression": analysis["equilibrium_expression"],
                "artifacts": published,
                "claim_ids": [item["claim"]["claim_id"] for item in claims],
                "claims": claims,
                "document": document,
                "error": "",
            }
            self._write_record(record)
            self._emit(
                event_run_id,
                task_id,
                "scientific.completed",
                {
                    "analysis_id": spec.analysis_id,
                    "case_count": record["case_count"],
                    "reference_verified": True,
                    "document_id": document["document_id"],
                },
            )
            self.events.emit_state_change(
                event_run_id,
                RunState.COMPLETED,
                task_id=task_id,
                analysis_id=spec.analysis_id,
                document_id=document["document_id"],
            )
            return self.get(spec.analysis_id)
        except Exception as exc:
            self._release_environment(environment_id, best_effort=True)
            self._write_record(
                {
                    "schema_version": SCIENTIFIC_RESULT_SCHEMA_VERSION,
                    **spec.to_dict(),
                    "spec_sha256": spec.digest(),
                    "state": "failed",
                    "started_at": started_at,
                    "completed_at": _utc_now(),
                    "simulation_id": str(simulation_run.get("simulation_id") or ""),
                    "event_run_id": event_run_id,
                    "environment_id": environment_id,
                    "execution_run_id": str(execution.get("operation_run_id") or ""),
                    "artifacts": [],
                    "claim_ids": [],
                    "claims": [],
                    "document": None,
                    "error": str(exc)[:4096],
                }
            )
            self._emit(
                event_run_id,
                task_id,
                "scientific.failed",
                {"analysis_id": spec.analysis_id, "error": str(exc)[:2048]},
            )
            self.events.emit_state_change(
                event_run_id,
                RunState.FAILED,
                task_id=task_id,
                analysis_id=spec.analysis_id,
                error=str(exc),
            )
            raise

    def get(self, analysis_id: str) -> dict[str, Any]:
        _validate_analysis_id(analysis_id)
        path = self.storage / f"{analysis_id}.json"
        if not path.is_file():
            raise ScientificNotFoundError(
                f"Scientific analysis not found: {analysis_id}"
            )
        return self._read_record(path)

    def list_analyses(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(
            self.storage.glob("analysis_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                records.append(self._read_record(path))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                records.append(
                    {"analysis_id": path.stem, "state": "invalid", "error": str(exc)}
                )
        return records

    def _create_environment(
        self, spec: ScientificAnalysisSpec, run_id: str
    ) -> dict[str, Any]:
        created = self.environments.create(
            {
                "environment_type": "local_sandbox",
                "provider": "local-sandbox",
                "os": "windows",
                "cpu_limit": 2.0,
                "memory_limit_mb": 2048,
                "gpu_policy": "none",
                "network_policy": {"mode": "none"},
                "filesystem_policy": {
                    "read_only_root": True,
                    "temporary_filesystem_mb": 256,
                },
                "device_policy": {"gpu": "none", "devices": []},
                "workspace_mounts": [],
                "lifetime_seconds": 900,
                "task_id": spec.task_id or f"scientific:{spec.analysis_id}",
                "run_id": run_id,
                "trace_id": spec.trace_id,
            }
        )
        return self.environments.start(str(created["environment_id"]))

    def _release_environment(
        self, environment_id: str, *, best_effort: bool = False
    ) -> None:
        if not environment_id:
            return
        try:
            state = self.environments.get(environment_id).get("state")
            if state in {"ready", "running", "suspended"}:
                self.environments.stop(environment_id)
            if self.environments.get(environment_id).get("state") != "destroyed":
                self.environments.destroy(environment_id)
        except Exception:
            if not best_effort:
                raise

    @staticmethod
    def _simulation_artifact(run: Mapping[str, Any], name: str) -> dict[str, Any]:
        matches = [
            item
            for item in list(run.get("artifacts") or [])
            if item.get("name") == name
        ]
        if len(matches) != 1:
            raise ScientificValidationError(
                f"Simulation run does not contain exactly one {name} artifact"
            )
        return dict(matches[0])

    def _verified_artifact_bytes(self, artifact: Mapping[str, Any]) -> bytes:
        target = (self.root / str(artifact.get("location") or "")).resolve()
        if not _below(self.root, target) or not target.is_file() or target.is_symlink():
            raise ScientificValidationError(
                "Simulation artifact is outside the active workspace"
            )
        data = target.read_bytes()
        if len(data) > 20_000_000:
            raise ScientificValidationError("Simulation artifact exceeds 20 MB")
        if hashlib.sha256(data).hexdigest() != str(artifact.get("sha256") or ""):
            raise ScientificValidationError("Simulation artifact digest mismatch")
        registered = self.artifacts.get(str(artifact.get("artifact_id") or ""))
        if registered is None or registered.location != artifact.get("location"):
            raise ScientificValidationError("Simulation artifact is not registered")
        return data

    def _publish(
        self,
        spec: ScientificAnalysisSpec,
        run_id: str,
        task_id: str,
        name: str,
        data: bytes,
    ) -> dict[str, Any]:
        if len(data) > 20_000_000:
            raise ScientificValidationError("scientific output exceeds 20 MB")
        target = (self.outputs / spec.analysis_id / name).resolve()
        if not _below(self.outputs.resolve(), target):
            raise ScientificValidationError(
                "scientific output escaped Artifact storage"
            )
        _atomic_bytes(target, data)
        digest = hashlib.sha256(data).hexdigest()
        artifact = self.artifacts.create(
            ArtifactType.DATASET if name.endswith(".csv") else ArtifactType.REPORT,
            f"Scientific {name}: {spec.analysis_id}",
            location=target.relative_to(self.root).as_posix(),
            creator="scientific.runtime",
            metadata={
                "analysis_id": spec.analysis_id,
                "simulation_run_id": spec.simulation_run_id,
                "format": target.suffix.lstrip("."),
                "sha256": digest,
                "size_bytes": len(data),
                "analysis_type": spec.analysis_type,
            },
        )
        self._emit(
            run_id,
            task_id,
            "artifact.created",
            {
                "artifact_id": artifact.id,
                "artifact_type": artifact.type,
                "location": artifact.location,
                "analysis_id": spec.analysis_id,
            },
        )
        return {
            "name": name,
            "location": artifact.location,
            "size_bytes": len(data),
            "sha256": digest,
            "artifact_id": artifact.id,
        }

    def _create_claims(
        self,
        spec: ScientificAnalysisSpec,
        analysis: Mapping[str, Any],
        analysis_artifact_id: str,
        simulation_artifact_id: str,
        run_id: str,
        task_id: str,
    ) -> list[dict[str, Any]]:
        claims = []
        # Reload the registry after publishing analysis outputs so the Claim
        # authority validates the newly registered artifact identifiers.
        research = ResearchEvidenceService(self.root)
        for item in list(analysis.get("cases") or []):
            case_id = int(item["case_id"])
            condition = (
                "remained within"
                if item["safe_during_simulated_duration"]
                else "exceeded"
            )
            statement = (
                f"Thermal case {case_id} {condition} the declared safety limit "
                f"during the simulated duration, with peak "
                f"{float(item['peak_temperature_kelvin']):.6f} K and margin "
                f"{float(item['mission_safety_margin_kelvin']):.6f} K."
            )
            claim = research.create_claim(
                {
                    "statement": statement,
                    "task_id": task_id,
                    "run_id": run_id,
                    "trace_id": spec.trace_id,
                    "confidence": 1.0,
                    "created_by": "scientific.runtime",
                    "evidence": [
                        {
                            "artifact_ref": simulation_artifact_id,
                            "relation": "derived_from",
                            "strength": 1.0,
                            "description": "Governed Simulation result artifact.",
                            "provenance": {
                                "simulation_run_id": spec.simulation_run_id,
                                "case_id": case_id,
                            },
                        },
                        {
                            "artifact_ref": analysis_artifact_id,
                            "relation": "supports",
                            "strength": 1.0,
                            "description": "Independent SciPy reference validation artifact.",
                            "provenance": {
                                "analysis_id": spec.analysis_id,
                                "case_id": case_id,
                            },
                        },
                    ],
                    "provenance": {
                        "analysis_id": spec.analysis_id,
                        "analysis_type": spec.analysis_type,
                    },
                }
            )
            claims.append(
                research.verify_claim(
                    claim["claim"]["claim_id"],
                    {
                        "verification_state": "supported",
                        "verifier": "scientific.reference-verifier",
                        "provenance": {
                            "reference_solver": analysis["reference_solver"],
                            "reference_tolerance_kelvin": analysis[
                                "reference_tolerance_kelvin"
                            ],
                        },
                    },
                )
            )
        self._emit(
            run_id,
            task_id,
            "scientific.claims_created",
            {
                "analysis_id": spec.analysis_id,
                "claim_ids": [item["claim"]["claim_id"] for item in claims],
            },
        )
        return claims

    def _create_report(
        self,
        spec: ScientificAnalysisSpec,
        simulation: Mapping[str, Any],
        simulation_run: Mapping[str, Any],
        analysis: Mapping[str, Any],
        claims: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        run_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        rows = [
            [
                "Case",
                "Solar flux",
                "Peak K",
                "Final K",
                "Equilibrium K",
                "Safety margin K",
                "Reference max error K",
                "Verified",
            ]
        ]
        for item in analysis["cases"]:
            rows.append(
                [
                    str(item["case_id"]),
                    f"{float(item['parameters']['solar_flux']):.6g}",
                    f"{float(item['peak_temperature_kelvin']):.6f}",
                    f"{float(item['final_temperature_kelvin']):.6f}",
                    f"{float(item['radiative_equilibrium_kelvin']):.6f}",
                    f"{float(item['mission_safety_margin_kelvin']):.6f}",
                    f"{float(item['maximum_reference_error_kelvin']):.9f}",
                    "yes" if item["within_reference_tolerance"] else "no",
                ]
            )
        provider_items = [
            f"{name} {item['version']}: {', '.join(item['capabilities'])}"
            for name, item in sorted(analysis["provider_inventory"].items())
        ]
        claim_items = [
            f"{item['claim']['claim_id']} [{item['claim']['verification_state']}]: {item['claim']['statement']}"
            for item in claims
        ]
        artifact_items = [
            f"{item['artifact_id']} - {item['name']} - SHA-256 {item['sha256']}"
            for item in artifacts
        ]
        created = self.documents.create(
            {
                "title": "Spacecraft Thermal Analysis Technical Report",
                "subtitle": f"Analysis {spec.analysis_id} / Simulation run {spec.simulation_run_id}",
                "author": "Nous Scientific Runtime",
                "language": "en-US",
                "preset": "standard_business_brief",
                "blocks": [
                    {"kind": "heading", "level": 1, "text": "Executive summary"},
                    {
                        "kind": "paragraph",
                        "text": (
                            f"{analysis['case_count']} governed thermal cases were analyzed. "
                            f"Independent reference verification was "
                            f"{'successful' if analysis['reference_verified'] else 'not successful'}. "
                            f"All cases were "
                            f"{'within' if analysis['safe_during_simulated_duration'] else 'not within'} "
                            "the declared mission-duration safety limit."
                        ),
                    },
                    {"kind": "heading", "level": 1, "text": "Method"},
                    {
                        "kind": "paragraph",
                        "text": (
                            "The deterministic explicit-Euler spacecraft-thermal/v1 result "
                            "was produced inside a governed Environment. P20 independently "
                            "integrated the equation with SciPy DOP853, derived equilibrium "
                            "with SymPy, analyzed the dataset with pandas and NumPy, and "
                            "rendered the comparison with Matplotlib."
                        ),
                    },
                    {
                        "kind": "paragraph",
                        "text": (
                            f"Reference tolerance: {spec.reference_tolerance_kelvin:.9g} K. "
                            f"Equation: {analysis['equation']}"
                        ),
                    },
                    {"kind": "heading", "level": 1, "text": "Results"},
                    {"kind": "table", "rows": rows},
                    {"kind": "heading", "level": 1, "text": "Scientific providers"},
                    {"kind": "bullet_list", "items": provider_items},
                    {"kind": "heading", "level": 1, "text": "Verified claims"},
                    {"kind": "bullet_list", "items": claim_items},
                    {"kind": "heading", "level": 1, "text": "Provenance"},
                    {
                        "kind": "bullet_list",
                        "items": [
                            f"Simulation: {simulation['simulation_id']}",
                            f"Simulation run: {simulation_run['simulation_run_id']}",
                            f"Simulation result digest: {simulation_run['result_digest']}",
                            f"Analysis contract SHA-256: {spec.digest()}",
                            *artifact_items,
                        ],
                    },
                    {
                        "kind": "paragraph",
                        "text": (
                            "Evidence level: integrated-host on Windows 10 x64. The local "
                            "sandbox enforces process and resource controls but is not a "
                            "hard filesystem or network namespace."
                        ),
                    },
                ],
            }
        )
        rendered = self.documents.render(
            created["document_id"], formats=spec.report_formats
        )
        result = {
            "document_id": created["document_id"],
            "document_ir_artifact_id": created["artifact_id"],
            "document_run_id": created["run_id"],
            "render_run_id": rendered["run_id"],
            "verified": rendered["verified"],
            "outputs": rendered["outputs"],
        }
        self._emit(
            run_id,
            task_id,
            "scientific.report_rendered",
            {
                "analysis_id": spec.analysis_id,
                "document_id": result["document_id"],
                "artifact_ids": [item["artifact_id"] for item in result["outputs"]],
                "formats": list(spec.report_formats),
                "verified": result["verified"],
            },
        )
        return result

    def _start(self, run_id: str, task_id: str, metadata: dict[str, Any]) -> None:
        self.events.create_run(
            run_id,
            task_id=task_id,
            total_steps=1,
            metadata={
                "authority": "EventStream",
                "operation": "scientific.analyze",
                **metadata,
            },
        )
        self.events.emit_state_change(
            run_id,
            RunState.CREATED,
            task_id=task_id,
            operation="scientific.analyze",
            **metadata,
        )
        self.events.emit(
            RunEvent(
                run_id=run_id,
                task_id=task_id,
                event_type="command.proposed",
                actor="scientific.runtime",
                payload={"operation": "scientific.analyze", **metadata},
            )
        )
        self.events.emit_state_change(
            run_id, RunState.RUNNING, task_id=task_id, operation="scientific.analyze"
        )

    def _emit(
        self, run_id: str, task_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.events.emit(
            RunEvent(
                run_id=run_id,
                task_id=task_id,
                event_type=event_type,
                actor="scientific.runtime",
                payload=payload,
            )
        )

    def _write_record(self, value: Mapping[str, Any]) -> None:
        payload = dict(value)
        payload.pop("sha256", None)
        payload["sha256"] = _record_digest(payload)
        _atomic_json(self.storage / f"{payload['analysis_id']}.json", payload)

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any]:
        with file_lock(str(path) + ".lock"):
            value = json.loads(path.read_text(encoding="utf-8"))
        expected = str(value.pop("sha256", ""))
        if not expected or expected != _record_digest(value):
            raise ScientificValidationError(
                "Scientific analysis record digest mismatch"
            )
        return {**value, "sha256": expected}


def _worker_argv() -> list[str]:
    args = [
        "--input",
        "scientific-input.json",
        "--simulation-result",
        "simulation-result.json",
        "--series",
        "series.csv",
        "--output-dir",
        "outputs",
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, "scientific-worker", *args]
    return [sys.executable, "-m", "nous_runtime.scientific.worker", *args]


def _stage_worker_bundle(environments: EnvironmentRuntime, environment_id: str) -> None:
    sources = {
        "nous_runtime/__init__.py": b"",
        "nous_runtime/scientific/__init__.py": b"",
        "nous_runtime/scientific/providers.py": Path(__file__)
        .with_name("providers.py")
        .read_bytes(),
        "nous_runtime/scientific/worker.py": Path(__file__)
        .with_name("worker.py")
        .read_bytes(),
    }
    for relative_path, data in sources.items():
        environments.stage_file(
            environment_id, relative_path, data, max_bytes=1_000_000
        )


def _worker_code_hash() -> str:
    from nous_runtime.scientific import providers, worker

    names = (
        "_module_version",
        "provider_inventory",
        "require_providers",
        "analyze_spacecraft_thermal",
    )
    data = b"".join(marshal.dumps(getattr(providers, name).__code__) for name in names)
    return hashlib.sha256(data + marshal.dumps(worker.main.__code__)).hexdigest()


def _validate_analysis_id(value: str) -> None:
    if not re.fullmatch(r"analysis_[a-f0-9]{32}", str(value)):
        raise ScientificValidationError("analysis_id is invalid")


def _record_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=list,
        ).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with file_lock(str(path) + ".lock"):
        descriptor, temporary = tempfile.mkstemp(
            prefix=".nous-scientific-", suffix=".json", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".nous-scientific-", suffix=path.suffix, dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _below(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


__all__ = ["ScientificNotFoundError", "ScientificRuntime"]
