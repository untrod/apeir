"""Governed reproducible Simulation Runtime built on EnvironmentRuntime."""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import platform
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.artifact import ArtifactManager, ArtifactRegistry, ArtifactType
from nous_runtime.environments import EnvironmentRuntime
from nous_runtime.environments.contract import KERNEL_VERSION, NKI_PROTOCOL_VERSION
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.locking import file_lock
from nous_runtime.schema_registry import (
    ENVIRONMENT_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    SIMULATION_RUN_SCHEMA_VERSION,
)
from nous_runtime.simulations.models import SimulationSpec, SimulationValidationError
from nous_runtime.version import __version__


class SimulationNotFoundError(SimulationValidationError):
    """A requested Simulation specification or run does not exist."""


class SimulationRuntime:
    """Canonical workspace authority for Simulation workloads and replay."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise SimulationValidationError("the active workspace does not exist")
        base = self.root / ".nous" / "simulations"
        self.specs, self.runs, self.active = (
            base / "specs",
            base / "runs",
            base / "active",
        )
        self.outputs = self.root / "artifacts" / "simulations"
        for directory in (self.specs, self.runs, self.active, self.outputs):
            directory.mkdir(parents=True, exist_ok=True)
        self.environments = EnvironmentRuntime(self.root)
        self.events = EventStream(str(self.root))
        self.artifacts = ArtifactManager(
            ArtifactRegistry(self.root / ".nous" / "artifacts.jsonl")
        )

    def status(self) -> dict[str, Any]:
        runs = self.list_runs(limit=200)
        return {
            "schema_version": "nous.simulation-runtime/v1",
            "simulation_contract": "nous.simulation/v1",
            "simulation_run_contract": SIMULATION_RUN_SCHEMA_VERSION,
            "environment_contract": ENVIRONMENT_SCHEMA_VERSION,
            "workspace": str(self.root),
            "simulations": len(self.list_simulations()),
            "runs": len(runs),
            "completed": sum(item.get("state") == "completed" for item in runs),
            "failed": sum(item.get("state") == "failed" for item in runs),
            "active": len(tuple(self.active.glob("sim_*.json"))),
            "built_in_models": [
                {
                    "model_ref": "spacecraft-thermal/v1",
                    "solver": "explicit-euler",
                    "deterministic": True,
                    "evidence_level": "integrated-host",
                }
            ],
            "scientific_providers": _scientific_versions(),
            "event_authority": "EventStream",
            "artifact_authority": "ArtifactRegistry",
            "execution_authority": "EnvironmentRuntime",
            "defaults": {
                "network": "none",
                "provider": "local-sandbox",
                "max_cases": 32,
            },
            "limitations": [
                "The v1 reference worker supports spacecraft-thermal/v1 only.",
                "LocalSandbox is integrated-host, not a hard filesystem or network namespace.",
                "OCI execution awaits an installed engine and governed container file transfer.",
            ],
        }

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        spec = SimulationSpec.from_mapping(value, new_identity=True)
        event_run_id = f"simulation-create-{uuid4().hex}"
        task_id = spec.task_id or f"simulation.create:{spec.simulation_id}"
        self._start_run(
            event_run_id,
            task_id,
            "simulation.create",
            {"simulation_id": spec.simulation_id},
        )
        try:
            path = self._spec_path(spec.simulation_id)
            self._atomic_json(path, {**spec.to_dict(), "sha256": spec.digest()})
            artifact = self.artifacts.create(
                ArtifactType.FILE,
                f"Simulation Contract: {spec.simulation_id}",
                location=path.relative_to(self.root).as_posix(),
                creator="simulation.runtime",
                metadata={
                    "simulation_id": spec.simulation_id,
                    "sha256": spec.digest(),
                    "model_ref": spec.model_ref,
                },
            )
            self._emit(
                event_run_id,
                task_id,
                "simulation.created",
                {
                    "simulation_id": spec.simulation_id,
                    "model_ref": spec.model_ref,
                    "spec_sha256": spec.digest(),
                },
            )
            self._artifact_event(event_run_id, task_id, artifact, spec.simulation_id)
            self.events.emit_state_change(
                event_run_id,
                RunState.COMPLETED,
                task_id=task_id,
                simulation_id=spec.simulation_id,
                artifact_id=artifact.id,
            )
            return {
                **spec.to_dict(),
                "sha256": spec.digest(),
                "artifact_id": artifact.id,
                "operation_run_id": event_run_id,
            }
        except Exception as exc:
            self.events.emit_state_change(
                event_run_id,
                RunState.FAILED,
                task_id=task_id,
                simulation_id=spec.simulation_id,
                error=str(exc),
            )
            raise

    def get(self, simulation_id: str) -> dict[str, Any]:
        spec = self._load_spec(simulation_id)
        return {**spec.to_dict(), "sha256": spec.digest()}

    def list_simulations(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(
            self.specs.glob("sim_*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        ):
            try:
                spec = self._read_spec(path)
                result.append({**spec.to_dict(), "sha256": spec.digest()})
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                result.append(
                    {"simulation_id": path.stem, "state": "invalid", "error": str(exc)}
                )
        return result

    def list_runs(
        self, simulation_id: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        if simulation_id:
            self._validate_simulation_id(simulation_id)
            paths = (self.runs / simulation_id).glob("simrun_*.json")
        else:
            paths = self.runs.glob("sim_*/simrun_*.json")
        ordered = sorted(paths, key=lambda item: item.stat().st_mtime_ns, reverse=True)
        result: list[dict[str, Any]] = []
        for path in ordered[: max(1, min(int(limit), 200))]:
            try:
                result.append(self._read_run(path))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                result.append(
                    {
                        "simulation_run_id": path.stem,
                        "state": "invalid",
                        "error": str(exc),
                    }
                )
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        matches = tuple(self.runs.glob(f"sim_*/{run_id}.json"))
        if len(matches) != 1:
            raise SimulationNotFoundError(f"Simulation run not found: {run_id}")
        return self._read_run(matches[0])

    def run(self, simulation_id: str, *, replay_of: str = "") -> dict[str, Any]:
        spec = self._load_spec(simulation_id)
        if spec.model_ref != "spacecraft-thermal/v1":
            raise SimulationValidationError("unsupported Simulation model_ref")
        if spec.provider != "local-sandbox":
            raise SimulationValidationError(
                "OCI Simulation awaits governed container file transfer"
            )
        original = self.get_run(replay_of) if replay_of else None
        if original and original.get("simulation_id") != simulation_id:
            raise SimulationValidationError(
                "replay run belongs to a different Simulation"
            )
        simulation_run_id = f"simrun_{uuid4().hex}"
        event_run_id = f"simulation-run-{uuid4().hex}"
        task_id = spec.task_id or f"simulation.run:{simulation_id}"
        started_at = _utc_now()
        operation = "simulation.replay" if replay_of else "simulation.run"
        self._start_run(
            event_run_id,
            task_id,
            operation,
            {
                "simulation_id": simulation_id,
                "simulation_run_id": simulation_run_id,
                "replay_of": replay_of,
            },
        )
        self._emit(
            event_run_id,
            task_id,
            "simulation.started",
            {
                "simulation_id": simulation_id,
                "simulation_run_id": simulation_run_id,
                "model_ref": spec.model_ref,
                "seed": spec.seed,
                "case_count": len(spec.cases()),
            },
        )
        environment_id, owned, started_existing = "", False, False
        attempts: list[dict[str, Any]] = []
        active_path = self._active_path(simulation_id)
        try:
            environment, owned, started_existing = self._acquire_environment(
                spec, simulation_run_id
            )
            environment_id = str(environment["environment_id"])
            input_name = f"simulation-input-{simulation_run_id}.json"
            output_dir = f"outputs/{simulation_run_id}"
            cancel_name = f"cancel-{simulation_run_id}.flag"
            staged = self.environments.stage_file(
                environment_id,
                input_name,
                (
                    json.dumps(
                        {**spec.to_dict(), "sha256": spec.digest()},
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode(),
            )
            if not getattr(sys, "frozen", False):
                _stage_worker_bundle(self.environments, environment_id)
            self._atomic_json(
                active_path,
                {
                    "schema_version": "nous.simulation-active/v1",
                    "simulation_id": simulation_id,
                    "simulation_run_id": simulation_run_id,
                    "environment_id": environment_id,
                    "cancel_path": cancel_name,
                    "started_at": started_at,
                },
            )
            execution: dict[str, Any] = {}
            for attempt_number in range(1, spec.resource_budget.max_retries + 2):
                execution = self.environments.run(
                    environment_id,
                    {
                        "argv": _worker_argv(input_name, output_dir, cancel_name),
                        "cancel_file": cancel_name,
                        "cwd": ".",
                        "timeout_seconds": spec.resource_budget.wall_time_seconds,
                        "max_output_bytes": min(
                            spec.resource_budget.max_output_bytes, 2_000_000
                        ),
                    },
                )
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "ok": bool(execution.get("ok")),
                        "exit_code": int(execution.get("exit_code", -1)),
                        "timed_out": bool(execution.get("timed_out", False)),
                        "operation_run_id": str(
                            execution.get("operation_run_id") or ""
                        ),
                        "artifact_id": str(execution.get("artifact_id") or ""),
                    }
                )
                if execution.get("ok") or int(execution.get("exit_code", -1)) == 130:
                    break
                if attempt_number <= spec.resource_budget.max_retries:
                    self._emit(
                        event_run_id,
                        task_id,
                        "simulation.retrying",
                        {
                            "simulation_id": simulation_id,
                            "simulation_run_id": simulation_run_id,
                            "attempt": attempt_number,
                            "max_retries": spec.resource_budget.max_retries,
                        },
                    )
            if not execution.get("ok"):
                if int(execution.get("exit_code", -1)) == 130:
                    return self._cancelled(
                        spec,
                        simulation_run_id,
                        event_run_id,
                        task_id,
                        environment_id,
                        started_at,
                        owned,
                        started_existing,
                        attempts,
                    )
                if execution.get("timed_out"):
                    raise SimulationValidationError("Simulation worker timed out")
                raise SimulationValidationError(
                    f"Simulation worker failed: {str(execution.get('stderr') or '')[:1024]}"
                )
            worker_bytes = self.environments.read_file(
                environment_id,
                f"{output_dir}/result.json",
                max_bytes=spec.resource_budget.max_output_bytes,
            )
            worker_result = json.loads(worker_bytes.decode())
            if worker_result.get("simulation_id") != simulation_id:
                raise SimulationValidationError(
                    "Simulation worker returned a mismatched identity"
                )
            published: list[dict[str, Any]] = []
            for name in _output_names(spec):
                data = (
                    worker_bytes
                    if name == "result.json"
                    else self.environments.read_file(
                        environment_id,
                        f"{output_dir}/{name}",
                        max_bytes=spec.resource_budget.max_output_bytes,
                    )
                )
                published.append(
                    self._publish(
                        spec, simulation_run_id, event_run_id, task_id, name, data
                    )
                )
            self._release_environment(environment_id, owned, started_existing)
            environment = self.environments.get(environment_id)
            reproducibility = self._reproducibility(
                spec, environment, staged, worker_result
            )
            replay = (
                self._compare_replay(original, worker_result, reproducibility, spec)
                if original
                else None
            )
            manifest = self.artifacts.create(
                ArtifactType.REPORT,
                f"Simulation Run: {simulation_run_id}",
                location=self._run_path(simulation_id, simulation_run_id)
                .relative_to(self.root)
                .as_posix(),
                creator="simulation.runtime",
                metadata={
                    "simulation_id": simulation_id,
                    "simulation_run_id": simulation_run_id,
                    "replay_of": replay_of,
                },
            )
            result = {
                "schema_version": SIMULATION_RUN_SCHEMA_VERSION,
                "simulation_id": simulation_id,
                "simulation_run_id": simulation_run_id,
                "event_run_id": event_run_id,
                "state": "completed",
                "replay_of": replay_of,
                "started_at": started_at,
                "completed_at": _utc_now(),
                "model_ref": spec.model_ref,
                "solver": spec.solver,
                "environment_id": environment_id,
                "environment_owned": owned,
                "execution_run_id": execution.get("operation_run_id", ""),
                "execution_artifact_id": execution.get("artifact_id", ""),
                "execution_attempts": attempts,
                "spec_sha256": spec.digest(),
                "case_count": int(worker_result.get("case_count", 0)),
                "cases": list(worker_result.get("cases") or []),
                "result_digest": str(worker_result.get("result_digest") or ""),
                "artifacts": published,
                "manifest_artifact_id": manifest.id,
                "reproducibility": reproducibility,
                "replay": replay,
            }
            self._write_run(result)
            self._artifact_event(event_run_id, task_id, manifest, simulation_id)
            if replay:
                self._emit(
                    event_run_id,
                    task_id,
                    "simulation.replayed",
                    {
                        "simulation_id": simulation_id,
                        "simulation_run_id": simulation_run_id,
                        **replay,
                    },
                )
            self._emit(
                event_run_id,
                task_id,
                "simulation.completed",
                {
                    "simulation_id": simulation_id,
                    "simulation_run_id": simulation_run_id,
                    "case_count": result["case_count"],
                    "result_digest": result["result_digest"],
                    "artifact_ids": [item["artifact_id"] for item in published],
                },
            )
            self.events.emit_state_change(
                event_run_id,
                RunState.COMPLETED,
                task_id=task_id,
                simulation_id=simulation_id,
                simulation_run_id=simulation_run_id,
                artifact_id=manifest.id,
            )
            return result
        except Exception as exc:
            self._release_environment(
                environment_id, owned, started_existing, best_effort=True
            )
            result = {
                "schema_version": SIMULATION_RUN_SCHEMA_VERSION,
                "simulation_id": simulation_id,
                "simulation_run_id": simulation_run_id,
                "event_run_id": event_run_id,
                "state": "failed",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "environment_id": environment_id,
                "execution_attempts": attempts,
                "spec_sha256": spec.digest(),
                "error": str(exc)[:2048],
                "artifacts": [],
                "cases": [],
            }
            self._write_run(result)
            self._emit(
                event_run_id,
                task_id,
                "simulation.failed",
                {
                    "simulation_id": simulation_id,
                    "simulation_run_id": simulation_run_id,
                    "error": str(exc)[:2048],
                },
            )
            self.events.emit_state_change(
                event_run_id,
                RunState.FAILED,
                task_id=task_id,
                simulation_id=simulation_id,
                error=str(exc),
            )
            raise
        finally:
            active_path.unlink(missing_ok=True)

    def replay(self, run_id: str) -> dict[str, Any]:
        original = self.get_run(run_id)
        if original.get("state") != "completed":
            raise SimulationValidationError(
                "only completed Simulation runs can be replayed"
            )
        return self.run(str(original["simulation_id"]), replay_of=run_id)

    def cancel(self, simulation_id: str) -> dict[str, Any]:
        path = self._active_path(simulation_id)
        if not path.is_file():
            raise SimulationValidationError("Simulation has no active run")
        value = json.loads(path.read_text(encoding="utf-8"))
        self.environments.stage_file(
            str(value.get("environment_id") or ""),
            str(value.get("cancel_path") or ""),
            b"cancel\n",
            max_bytes=64,
        )
        return {
            "simulation_id": simulation_id,
            "simulation_run_id": str(value.get("simulation_run_id") or ""),
            "cancellation_requested": True,
        }

    def _cancelled(
        self,
        spec: SimulationSpec,
        run_id: str,
        event_run_id: str,
        task_id: str,
        environment_id: str,
        started_at: str,
        owned: bool,
        started_existing: bool,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._release_environment(
            environment_id, owned, started_existing, best_effort=True
        )
        result = {
            "schema_version": SIMULATION_RUN_SCHEMA_VERSION,
            "simulation_id": spec.simulation_id,
            "simulation_run_id": run_id,
            "event_run_id": event_run_id,
            "state": "cancelled",
            "started_at": started_at,
            "completed_at": _utc_now(),
            "environment_id": environment_id,
            "execution_attempts": attempts,
            "spec_sha256": spec.digest(),
            "artifacts": [],
            "cases": [],
        }
        self._write_run(result)
        self._emit(
            event_run_id,
            task_id,
            "simulation.cancelled",
            {"simulation_id": spec.simulation_id, "simulation_run_id": run_id},
        )
        self.events.emit_state_change(
            event_run_id,
            RunState.CANCELLED,
            task_id=task_id,
            simulation_id=spec.simulation_id,
        )
        return result

    def _acquire_environment(
        self, spec: SimulationSpec, simulation_run_id: str
    ) -> tuple[dict[str, Any], bool, bool]:
        if spec.environment_ref:
            environment = self.environments.get(spec.environment_ref)
            if environment.get("provider") != spec.provider:
                raise SimulationValidationError(
                    "environment_ref provider does not match Simulation"
                )
            if environment.get("state") == "ready":
                return environment, False, False
            if environment.get("state") in {"created", "stopped", "failed"}:
                return self.environments.start(spec.environment_ref), False, True
            raise SimulationValidationError("environment_ref is not available")
        created = self.environments.create(
            {
                "environment_type": spec.environment_type,
                "provider": spec.provider,
                "image": spec.image,
                "os": "linux"
                if spec.environment_type == "oci_container"
                else "windows",
                "cpu_limit": spec.resource_budget.cpu_limit,
                "memory_limit_mb": spec.resource_budget.memory_limit_mb,
                "gpu_policy": "none",
                "network_policy": {"mode": "none"},
                "filesystem_policy": {
                    "read_only_root": True,
                    "temporary_filesystem_mb": 128,
                },
                "device_policy": {"gpu": "none", "devices": []},
                "workspace_mounts": [],
                "lifetime_seconds": min(
                    spec.resource_budget.wall_time_seconds + 300, 86400
                ),
                "task_id": spec.task_id or f"simulation:{spec.simulation_id}",
                "run_id": simulation_run_id,
                "trace_id": spec.trace_id,
            }
        )
        return self.environments.start(str(created["environment_id"])), True, False

    def _release_environment(
        self,
        environment_id: str,
        owned: bool,
        started_existing: bool,
        *,
        best_effort: bool = False,
    ) -> None:
        if not environment_id or not (owned or started_existing):
            return
        try:
            current = self.environments.get(environment_id)
            if current.get("state") in {"ready", "running", "suspended"}:
                self.environments.stop(environment_id)
            if (
                owned
                and self.environments.get(environment_id).get("state") != "destroyed"
            ):
                self.environments.destroy(environment_id)
        except Exception:
            if not best_effort:
                raise

    def _publish(
        self,
        spec: SimulationSpec,
        simulation_run_id: str,
        event_run_id: str,
        task_id: str,
        name: str,
        data: bytes,
    ) -> dict[str, Any]:
        if len(data) > spec.resource_budget.max_output_bytes:
            raise SimulationValidationError("Simulation output exceeds resource budget")
        target = (
            self.outputs / spec.simulation_id / simulation_run_id / name
        ).resolve()
        if not _below(self.outputs.resolve(), target):
            raise SimulationValidationError(
                "Simulation output escaped Artifact storage"
            )
        _atomic_bytes(target, data)
        digest = hashlib.sha256(data).hexdigest()
        artifact_type = (
            ArtifactType.DATASET
            if name.endswith(".csv")
            else ArtifactType.REPORT
            if name.endswith(".json")
            else ArtifactType.FILE
        )
        artifact = self.artifacts.create(
            artifact_type,
            f"Simulation {name}: {simulation_run_id}",
            location=target.relative_to(self.root).as_posix(),
            creator="simulation.runtime",
            metadata={
                "simulation_id": spec.simulation_id,
                "simulation_run_id": simulation_run_id,
                "format": target.suffix.lstrip("."),
                "sha256": digest,
                "size_bytes": len(data),
                "model_ref": spec.model_ref,
            },
        )
        self._artifact_event(event_run_id, task_id, artifact, spec.simulation_id)
        return {
            "name": name,
            "location": artifact.location,
            "size_bytes": len(data),
            "sha256": digest,
            "artifact_id": artifact.id,
        }

    def _reproducibility(
        self,
        spec: SimulationSpec,
        environment: Mapping[str, Any],
        staged: Mapping[str, Any],
        worker: Mapping[str, Any],
    ) -> dict[str, Any]:
        environment_fields = {
            key: environment.get(key)
            for key in (
                "provider",
                "environment_type",
                "image",
                "architecture",
                "os",
                "cpu_limit",
                "memory_limit_mb",
                "gpu_policy",
                "network_policy",
                "filesystem_policy",
                "device_policy",
                "workspace_mounts",
            )
        }
        return {
            "code_hash": _worker_code_hash(),
            "model_hash": _digest(
                {
                    "model_ref": spec.model_ref,
                    "model_version": worker.get("model_version"),
                }
            ),
            "input_hash": _digest(
                {
                    "initial_state": spec.initial_state,
                    "boundary_conditions": spec.boundary_conditions,
                }
            ),
            "parameter_hash": _digest(
                {"parameters": spec.parameters, "parameter_space": spec.parameter_space}
            ),
            "spec_hash": spec.digest(),
            "environment_contract_sha256": environment.get("sha256", ""),
            "environment_fingerprint": _digest(environment_fields),
            "container_image_digest": spec.image.split("@", 1)[1]
            if "@sha256:" in spec.image
            else "",
            "staged_input_sha256": staged.get("sha256", ""),
            "dependency_versions": dict(worker.get("dependency_versions") or {}),
            "seed": spec.seed,
            "runtime_version": __version__,
            "kernel_version": KERNEL_VERSION,
            "nki_version": NKI_PROTOCOL_VERSION,
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "cpu": platform.processor(),
            "gpu": "none",
            "architecture": platform.machine(),
            "os": platform.system(),
            "captured_at": _utc_now(),
            "numerical_tolerance": {
                "absolute": spec.numerical_tolerance.absolute,
                "relative": spec.numerical_tolerance.relative,
            },
        }

    @staticmethod
    def _compare_replay(
        original: Mapping[str, Any],
        worker: Mapping[str, Any],
        reproducibility: Mapping[str, Any],
        spec: SimulationSpec,
    ) -> dict[str, Any]:
        old_repro = dict(original.get("reproducibility") or {})
        keys = (
            "code_hash",
            "model_hash",
            "input_hash",
            "parameter_hash",
            "spec_hash",
            "environment_fingerprint",
            "seed",
        )
        matching = all(old_repro.get(key) == reproducibility.get(key) for key in keys)
        old_cases, new_cases = (
            list(original.get("cases") or []),
            list(worker.get("cases") or []),
        )
        within, maximum = len(old_cases) == len(new_cases), 0.0
        if within:
            for left, right in zip(old_cases, new_cases, strict=True):
                left_metrics, right_metrics = (
                    dict(left.get("metrics") or {}),
                    dict(right.get("metrics") or {}),
                )
                if set(left_metrics) != set(right_metrics):
                    within = False
                    break
                for key, value in left_metrics.items():
                    a, b = float(value), float(right_metrics[key])
                    error = abs(a - b)
                    maximum = max(maximum, error)
                    limit = (
                        spec.numerical_tolerance.absolute
                        + spec.numerical_tolerance.relative * max(abs(a), abs(b))
                    )
                    if error > limit:
                        within = False
        return {
            "verified": matching and within,
            "matching_contract": matching,
            "within_tolerance": within,
            "maximum_absolute_error": maximum,
            "absolute_tolerance": spec.numerical_tolerance.absolute,
            "relative_tolerance": spec.numerical_tolerance.relative,
        }

    def _load_spec(self, simulation_id: str) -> SimulationSpec:
        path = self._spec_path(simulation_id)
        if not path.is_file():
            raise SimulationNotFoundError(f"Simulation not found: {simulation_id}")
        return self._read_spec(path)

    @staticmethod
    def _read_spec(path: Path) -> SimulationSpec:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = str(value.pop("sha256", ""))
        spec = SimulationSpec.from_mapping(value)
        if not expected or expected != spec.digest():
            raise SimulationValidationError("Simulation spec digest mismatch")
        return spec

    def _write_run(self, value: dict[str, Any]) -> None:
        payload = dict(value)
        payload.pop("sha256", None)
        payload["sha256"] = _digest(payload)
        self._atomic_json(
            self._run_path(
                str(value["simulation_id"]), str(value["simulation_run_id"])
            ),
            payload,
        )
        value["sha256"] = payload["sha256"]

    @staticmethod
    def _read_run(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = str(value.pop("sha256", ""))
        if not expected or expected != _digest(value):
            raise SimulationValidationError("Simulation run digest mismatch")
        return {**value, "sha256": expected}

    def _spec_path(self, simulation_id: str) -> Path:
        self._validate_simulation_id(simulation_id)
        return self.specs / f"{simulation_id}.json"

    def _run_path(self, simulation_id: str, run_id: str) -> Path:
        self._validate_simulation_id(simulation_id)
        self._validate_run_id(run_id)
        return self.runs / simulation_id / f"{run_id}.json"

    def _active_path(self, simulation_id: str) -> Path:
        self._validate_simulation_id(simulation_id)
        return self.active / f"{simulation_id}.json"

    @staticmethod
    def _validate_simulation_id(value: str) -> None:
        if not re.fullmatch(r"sim_[a-f0-9]{32}", str(value)):
            raise SimulationValidationError("simulation_id is invalid")

    @staticmethod
    def _validate_run_id(value: str) -> None:
        if not re.fullmatch(r"simrun_[a-f0-9]{32}", str(value)):
            raise SimulationValidationError("simulation run_id is invalid")

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        _atomic_bytes(
            path,
            (
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            ).encode(),
        )

    def _start_run(
        self, run_id: str, task_id: str, operation: str, metadata: Mapping[str, Any]
    ) -> None:
        self.events.create_run(
            run_id,
            task_id=task_id,
            total_steps=1,
            metadata={
                "authority": "EventStream",
                "operation": operation,
                **dict(metadata),
            },
        )
        self.events.emit_state_change(
            run_id, RunState.CREATED, task_id=task_id, operation=operation
        )
        self._emit(
            run_id,
            task_id,
            "command.proposed",
            {"operation": operation, **dict(metadata)},
        )
        self.events.emit_state_change(
            run_id, RunState.RUNNING, task_id=task_id, operation=operation
        )

    def _emit(
        self, run_id: str, task_id: str, event_type: str, payload: Mapping[str, Any]
    ) -> None:
        self.events.emit(
            RunEvent(
                run_id=run_id,
                task_id=task_id,
                event_type=event_type,
                actor="simulation.runtime",
                payload=dict(payload),
            )
        )

    def _artifact_event(
        self, run_id: str, task_id: str, artifact, simulation_id: str
    ) -> None:
        self._emit(
            run_id,
            task_id,
            "artifact.created",
            {
                "artifact_id": artifact.id,
                "artifact_type": artifact.type,
                "location": artifact.location,
                "simulation_id": simulation_id,
            },
        )


def _worker_code_hash() -> str:
    from nous_runtime.simulations import worker

    names = ("_required", "_thermal_case", "_svg", "execute_payload", "main")
    payload = b"".join(marshal.dumps(getattr(worker, name).__code__) for name in names)
    payload += worker.MODEL_VERSION.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stage_worker_bundle(environments: EnvironmentRuntime, environment_id: str) -> None:
    package_root = Path(__file__).resolve().parents[1]
    sources = {
        "nous_runtime/__init__.py": b"",
        "nous_runtime/_version.py": (package_root / "_version.py").read_bytes(),
        "nous_runtime/schema_registry.py": (
            package_root / "schema_registry.py"
        ).read_bytes(),
        "nous_runtime/simulations/__init__.py": b"",
        "nous_runtime/simulations/models.py": Path(__file__)
        .with_name("models.py")
        .read_bytes(),
        "nous_runtime/simulations/worker.py": Path(__file__)
        .with_name("worker.py")
        .read_bytes(),
    }
    for relative_path, content in sources.items():
        environments.stage_file(
            environment_id, relative_path, content, max_bytes=1_000_000
        )


def _worker_argv(input_name: str, output_dir: str, cancel_name: str) -> list[str]:
    args = [
        "--input",
        input_name,
        "--output-dir",
        output_dir,
        "--cancel-file",
        cancel_name,
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, "simulation-worker", *args]
    return [sys.executable, "-m", "nous_runtime.simulations.worker", *args]


def _output_names(spec: SimulationSpec) -> list[str]:
    result = ["result.json"]
    if "csv" in spec.output_schema:
        result.append("series.csv")
    if "svg" in spec.output_schema:
        result.append("temperature.svg")
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=list,
        ).encode()
    ).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _below(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(str(path) + ".lock"):
        descriptor, temporary = tempfile.mkstemp(
            prefix=".nous-simulation-", dir=path.parent
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


def _scientific_versions() -> dict[str, str]:
    from nous_runtime.scientific.providers import provider_inventory

    return {
        name: str(item["version"] or "unavailable")
        if item["available"]
        else "unavailable"
        for name, item in provider_inventory().items()
    }


__all__ = ["SimulationNotFoundError", "SimulationRuntime"]
