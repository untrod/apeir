"""Strict contracts for governed scientific analyses."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.schema_registry import SCIENTIFIC_ANALYSIS_SCHEMA_VERSION

_ANALYSIS_ID = re.compile(r"^analysis_[a-f0-9]{32}$")
_SIMULATION_RUN_ID = re.compile(r"^simrun_[a-f0-9]{32}$")
_ALLOWED_FIELDS = {
    "schema_version",
    "analysis_id",
    "analysis_type",
    "simulation_run_id",
    "reference_solver",
    "reference_tolerance_kelvin",
    "report_formats",
    "task_id",
    "trace_id",
    "created_at",
}
_FORMATS = {"docx", "pdf"}


class ScientificValidationError(ValueError):
    """A scientific analysis contract or record is invalid."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class ScientificAnalysisSpec:
    schema_version: str
    analysis_id: str
    analysis_type: str
    simulation_run_id: str
    reference_solver: str
    reference_tolerance_kelvin: float
    report_formats: tuple[str, ...]
    task_id: str
    trace_id: str
    created_at: str

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, new_identity: bool = False
    ) -> "ScientificAnalysisSpec":
        if not isinstance(value, Mapping):
            raise ScientificValidationError("scientific analysis must be an object")
        unknown = set(value) - _ALLOWED_FIELDS
        if unknown:
            raise ScientificValidationError(
                f"unknown scientific analysis fields: {sorted(unknown)}"
            )
        schema = str(value.get("schema_version") or SCIENTIFIC_ANALYSIS_SCHEMA_VERSION)
        if schema != SCIENTIFIC_ANALYSIS_SCHEMA_VERSION:
            raise ScientificValidationError(f"unsupported schema_version: {schema}")
        analysis_id = (
            f"analysis_{uuid4().hex}"
            if new_identity
            else str(value.get("analysis_id") or "")
        )
        if not _ANALYSIS_ID.fullmatch(analysis_id):
            raise ScientificValidationError("analysis_id is invalid")
        simulation_run_id = str(value.get("simulation_run_id") or "")
        if not _SIMULATION_RUN_ID.fullmatch(simulation_run_id):
            raise ScientificValidationError("simulation_run_id is invalid")
        analysis_type = str(
            value.get("analysis_type") or "spacecraft-thermal-analysis/v1"
        )
        if analysis_type != "spacecraft-thermal-analysis/v1":
            raise ScientificValidationError("unsupported analysis_type")
        reference_solver = str(value.get("reference_solver") or "scipy.solve_ivp")
        if reference_solver != "scipy.solve_ivp":
            raise ScientificValidationError("unsupported reference_solver")
        raw_tolerance = value.get("reference_tolerance_kelvin", 0.05)
        if isinstance(raw_tolerance, bool):
            raise ScientificValidationError(
                "reference_tolerance_kelvin must be numeric"
            )
        try:
            tolerance = float(raw_tolerance)
        except (TypeError, ValueError) as exc:
            raise ScientificValidationError(
                "reference_tolerance_kelvin must be numeric"
            ) from exc
        if not math.isfinite(tolerance) or not 1.0e-6 <= tolerance <= 10.0:
            raise ScientificValidationError(
                "reference_tolerance_kelvin must be between 1e-6 and 10"
            )
        raw_formats = value.get("report_formats") or ("docx", "pdf")
        if not isinstance(raw_formats, (list, tuple)):
            raise ScientificValidationError("report_formats must be an array")
        formats = tuple(str(item).lower() for item in raw_formats)
        if (
            not formats
            or len(formats) != len(set(formats))
            or any(item not in _FORMATS for item in formats)
        ):
            raise ScientificValidationError(
                "report_formats must contain unique docx and/or pdf values"
            )
        return cls(
            schema_version=schema,
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            simulation_run_id=simulation_run_id,
            reference_solver=reference_solver,
            reference_tolerance_kelvin=tolerance,
            report_formats=formats,
            task_id=str(value.get("task_id") or "")[:128],
            trace_id=str(value.get("trace_id") or "")[:128],
            created_at=_utc_now()
            if new_identity
            else str(value.get("created_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["report_formats"] = list(self.report_formats)
        return value

    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["ScientificAnalysisSpec", "ScientificValidationError"]
