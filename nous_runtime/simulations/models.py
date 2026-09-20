"""Versioned, bounded contracts for reproducible Simulation workloads."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.schema_registry import SIMULATION_SCHEMA_VERSION

_ID = re.compile(r"^sim_[a-f0-9]{32}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,191}$")
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_ALLOWED_FIELDS = {
    "schema_version",
    "simulation_id",
    "model_ref",
    "environment_ref",
    "environment_type",
    "provider",
    "image",
    "initial_state",
    "boundary_conditions",
    "parameters",
    "solver",
    "time_step",
    "duration",
    "seed",
    "resource_budget",
    "network_policy",
    "metric_schema",
    "output_schema",
    "parameter_space",
    "numerical_tolerance",
    "task_id",
    "run_id",
    "trace_id",
    "created_at",
    "state",
    "last_error",
    "sha256",
}
_METRICS = {
    "peak_temperature",
    "equilibrium_temperature",
    "final_temperature",
    "safety_margin",
    "sample_count",
}
_OUTPUTS = {"json", "csv", "svg"}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise SimulationValidationError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SimulationValidationError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SimulationValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return result


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    result = _number(value, name, minimum, maximum)
    if not result.is_integer():
        raise SimulationValidationError(f"{name} must be an integer")
    return int(result)


def _numeric_mapping(value: Any, name: str, *, max_items: int = 64) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > max_items:
        raise SimulationValidationError(f"{name} must be a bounded object")
    result: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if not _KEY.fullmatch(key):
            raise SimulationValidationError(f"{name} contains an invalid key")
        result[key] = _number(raw_value, f"{name}.{key}", -1.0e12, 1.0e12)
    return result


class SimulationValidationError(ValueError):
    """A Simulation contract or persisted record is invalid."""


class SimulationState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResourceBudget:
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    wall_time_seconds: int = 300
    max_cases: int = 32
    max_retries: int = 0
    max_output_bytes: int = 20_000_000

    @classmethod
    def from_mapping(cls, value: Any) -> "ResourceBudget":
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise SimulationValidationError("resource_budget must be an object")
        unknown = set(value) - {
            "cpu_limit",
            "memory_limit_mb",
            "wall_time_seconds",
            "max_cases",
            "max_retries",
            "max_output_bytes",
        }
        if unknown:
            raise SimulationValidationError(
                f"unknown resource_budget fields: {sorted(unknown)}"
            )
        return cls(
            cpu_limit=_number(value.get("cpu_limit", 1.0), "cpu_limit", 0.1, 16.0),
            memory_limit_mb=_integer(
                value.get("memory_limit_mb", 512), "memory_limit_mb", 64, 16384
            ),
            wall_time_seconds=_integer(
                value.get("wall_time_seconds", 300), "wall_time_seconds", 1, 3600
            ),
            max_cases=_integer(value.get("max_cases", 32), "max_cases", 1, 64),
            max_retries=_integer(value.get("max_retries", 0), "max_retries", 0, 3),
            max_output_bytes=_integer(
                value.get("max_output_bytes", 20_000_000),
                "max_output_bytes",
                1024,
                50_000_000,
            ),
        )


@dataclass(frozen=True)
class NumericalTolerance:
    absolute: float = 1.0e-9
    relative: float = 1.0e-9

    @classmethod
    def from_mapping(cls, value: Any) -> "NumericalTolerance":
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise SimulationValidationError("numerical_tolerance must be an object")
        unknown = set(value) - {"absolute", "relative"}
        if unknown:
            raise SimulationValidationError(
                f"unknown numerical_tolerance fields: {sorted(unknown)}"
            )
        return cls(
            absolute=_number(
                value.get("absolute", 1.0e-9), "tolerance.absolute", 0.0, 1.0
            ),
            relative=_number(
                value.get("relative", 1.0e-9), "tolerance.relative", 0.0, 1.0
            ),
        )


@dataclass(frozen=True)
class SimulationSpec:
    schema_version: str
    simulation_id: str
    model_ref: str
    environment_ref: str
    environment_type: str
    provider: str
    image: str
    initial_state: dict[str, float]
    boundary_conditions: dict[str, float]
    parameters: dict[str, float]
    solver: str
    time_step: float
    duration: float
    seed: int
    resource_budget: ResourceBudget
    network_policy: dict[str, Any]
    metric_schema: tuple[str, ...]
    output_schema: tuple[str, ...]
    parameter_space: dict[str, tuple[float, ...]]
    numerical_tolerance: NumericalTolerance
    task_id: str
    run_id: str
    trace_id: str
    created_at: str
    state: SimulationState = SimulationState.CREATED
    last_error: str = ""

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, new_identity: bool = False
    ) -> "SimulationSpec":
        if not isinstance(value, Mapping):
            raise SimulationValidationError("simulation must be an object")
        unknown = set(value) - _ALLOWED_FIELDS
        if unknown:
            raise SimulationValidationError(
                f"unknown simulation fields: {sorted(unknown)}"
            )
        model_ref = str(value.get("model_ref") or "").strip()
        if not _REF.fullmatch(model_ref):
            raise SimulationValidationError("model_ref is invalid")
        simulation_id = (
            f"sim_{uuid4().hex}"
            if new_identity
            else str(value.get("simulation_id") or "")
        )
        if not _ID.fullmatch(simulation_id):
            raise SimulationValidationError("simulation_id is invalid")
        environment_ref = str(value.get("environment_ref") or "").strip()
        if environment_ref and not re.fullmatch(r"env_[a-f0-9]{32}", environment_ref):
            raise SimulationValidationError("environment_ref is invalid")
        environment_type = str(value.get("environment_type") or "local_sandbox")
        provider = str(value.get("provider") or "local-sandbox")
        if (environment_type, provider) not in {
            ("local_sandbox", "local-sandbox"),
            ("oci_container", "oci"),
        }:
            raise SimulationValidationError(
                "provider and environment_type are inconsistent"
            )
        image = str(value.get("image") or "").strip()
        if environment_type == "oci_container" and not image:
            raise SimulationValidationError("OCI simulations require an image")
        solver = str(value.get("solver") or "explicit-euler")
        if solver not in {"explicit-euler"}:
            raise SimulationValidationError("unsupported solver")
        budget = ResourceBudget.from_mapping(value.get("resource_budget"))
        network = value.get("network_policy") or {"mode": "none"}
        if not isinstance(network, Mapping) or set(network) - {"mode"}:
            raise SimulationValidationError("network_policy only supports mode")
        if str(network.get("mode") or "none") != "none":
            raise SimulationValidationError("Simulation network must be none in v1")
        metrics = tuple(
            str(item) for item in (value.get("metric_schema") or sorted(_METRICS))
        )
        if (
            not metrics
            or len(metrics) != len(set(metrics))
            or any(item not in _METRICS for item in metrics)
        ):
            raise SimulationValidationError(
                "metric_schema contains unsupported or duplicate metrics"
            )
        outputs = tuple(
            str(item) for item in (value.get("output_schema") or ("json", "csv", "svg"))
        )
        if (
            "json" not in outputs
            or len(outputs) != len(set(outputs))
            or any(item not in _OUTPUTS for item in outputs)
        ):
            raise SimulationValidationError(
                "output_schema must contain json and supported unique formats"
            )
        raw_space = value.get("parameter_space") or {}
        if not isinstance(raw_space, Mapping) or len(raw_space) > 8:
            raise SimulationValidationError("parameter_space must be a bounded object")
        space: dict[str, tuple[float, ...]] = {}
        case_count = 1
        for raw_key, raw_values in raw_space.items():
            key = str(raw_key)
            if (
                not _KEY.fullmatch(key)
                or not isinstance(raw_values, list)
                or not raw_values
                or len(raw_values) > 16
            ):
                raise SimulationValidationError(
                    "parameter_space contains an invalid dimension"
                )
            values = tuple(
                _number(item, f"parameter_space.{key}", -1.0e12, 1.0e12)
                for item in raw_values
            )
            space[key] = values
            case_count *= len(values)
        if case_count > budget.max_cases:
            raise SimulationValidationError(
                "parameter sweep exceeds resource_budget.max_cases"
            )
        return cls(
            schema_version=SIMULATION_SCHEMA_VERSION,
            simulation_id=simulation_id,
            model_ref=model_ref,
            environment_ref=environment_ref,
            environment_type=environment_type,
            provider=provider,
            image=image,
            initial_state=_numeric_mapping(value.get("initial_state"), "initial_state"),
            boundary_conditions=_numeric_mapping(
                value.get("boundary_conditions"), "boundary_conditions"
            ),
            parameters=_numeric_mapping(value.get("parameters"), "parameters"),
            solver=solver,
            time_step=_number(value.get("time_step", 1.0), "time_step", 1.0e-6, 3600.0),
            duration=_number(
                value.get("duration", 600.0), "duration", 1.0e-6, 31_536_000.0
            ),
            seed=_integer(value.get("seed", 0), "seed", 0, 2_147_483_647),
            resource_budget=budget,
            network_policy={"mode": "none"},
            metric_schema=metrics,
            output_schema=outputs,
            parameter_space=space,
            numerical_tolerance=NumericalTolerance.from_mapping(
                value.get("numerical_tolerance")
            ),
            task_id=str(value.get("task_id") or "").strip()[:128],
            run_id=str(value.get("run_id") or "").strip()[:128],
            trace_id=str(value.get("trace_id") or "").strip()[:128],
            created_at=_utc_now()
            if new_identity
            else str(value.get("created_at") or ""),
            state=SimulationState.CREATED
            if new_identity
            else SimulationState(str(value.get("state") or "created")),
            last_error=""
            if new_identity
            else str(value.get("last_error") or "")[:2048],
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        value["metric_schema"] = list(self.metric_schema)
        value["output_schema"] = list(self.output_schema)
        value["parameter_space"] = {
            key: list(values) for key, values in self.parameter_space.items()
        }
        return value

    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def cases(self) -> list[dict[str, float]]:
        if not self.parameter_space:
            return [dict(self.parameters)]
        keys = sorted(self.parameter_space)
        return [
            {**self.parameters, **dict(zip(keys, values, strict=True))}
            for values in itertools.product(
                *(self.parameter_space[key] for key in keys)
            )
        ]


__all__ = [
    "NumericalTolerance",
    "ResourceBudget",
    "SimulationSpec",
    "SimulationState",
    "SimulationValidationError",
]
