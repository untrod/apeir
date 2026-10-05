"""Durable Distribution-layer Work contracts for APEIR Compute Mesh."""

from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.locking import file_lock
from nous_runtime.security.private_files import restrict_owner_only_file


WORK_STORE_SCHEMA = "apeir.compute-mesh-works/v1"
WORK_SCHEMA = "apeir.compute-mesh-work/v1"


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class DistributedWorkError(ValueError):
    """Raised when a distributed Work contract or transition is invalid."""

    def __init__(
        self, message: str, *, workflow_output: Mapping[str, Any] | None = None
    ):
        super().__init__(message)
        self.workflow_output = dict(workflow_output or {})


class DistributedWorkState(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    VERIFIED = "VERIFIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    UNKNOWN = "UNKNOWN"


_TRANSITIONS: dict[DistributedWorkState, frozenset[DistributedWorkState]] = {
    DistributedWorkState.CREATED: frozenset(
        {DistributedWorkState.SCHEDULED, DistributedWorkState.FAILED}
    ),
    DistributedWorkState.SCHEDULED: frozenset(
        {DistributedWorkState.ASSIGNED, DistributedWorkState.FAILED}
    ),
    DistributedWorkState.ASSIGNED: frozenset(
        {
            DistributedWorkState.RUNNING,
            DistributedWorkState.FAILED,
            DistributedWorkState.RECOVERING,
            DistributedWorkState.UNKNOWN,
        }
    ),
    DistributedWorkState.RUNNING: frozenset(
        {
            DistributedWorkState.SUCCEEDED,
            DistributedWorkState.FAILED,
            DistributedWorkState.RECOVERING,
            DistributedWorkState.UNKNOWN,
        }
    ),
    DistributedWorkState.SUCCEEDED: frozenset(
        {
            DistributedWorkState.VERIFIED,
            DistributedWorkState.RECOVERING,
            DistributedWorkState.UNKNOWN,
        }
    ),
    DistributedWorkState.VERIFIED: frozenset(
        {DistributedWorkState.COMMITTED, DistributedWorkState.FAILED}
    ),
    DistributedWorkState.COMMITTED: frozenset(),
    DistributedWorkState.FAILED: frozenset({DistributedWorkState.RECOVERING}),
    DistributedWorkState.RECOVERING: frozenset(
        {
            DistributedWorkState.SCHEDULED,
            DistributedWorkState.ASSIGNED,
            DistributedWorkState.RUNNING,
            DistributedWorkState.FAILED,
            DistributedWorkState.UNKNOWN,
        }
    ),
    DistributedWorkState.UNKNOWN: frozenset(
        {DistributedWorkState.RECOVERING, DistributedWorkState.FAILED}
    ),
}


def _normalized_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip().lower() for item in values if item.strip()))


def _normalized_architectures(values: tuple[str, ...]) -> tuple[str, ...]:
    aliases = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "amd64": "amd64",
        "x64": "amd64",
        "x86_64": "amd64",
    }
    normalized = _normalized_values(values)
    return tuple(dict.fromkeys(aliases.get(item, item) for item in normalized))


@dataclass(frozen=True)
class WorkRequirements:
    architectures: tuple[str, ...] = ()
    operating_systems: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    minimum_memory_bytes: int = 0
    gpu_required: bool = False
    node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.minimum_memory_bytes < 0:
            raise DistributedWorkError("minimum memory cannot be negative")
        object.__setattr__(
            self, "architectures", _normalized_architectures(self.architectures)
        )
        object.__setattr__(
            self, "operating_systems", _normalized_values(self.operating_systems)
        )
        object.__setattr__(self, "capabilities", _normalized_values(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {
            "architectures": list(self.architectures),
            "operating_systems": list(self.operating_systems),
            "capabilities": list(self.capabilities),
            "minimum_memory_bytes": self.minimum_memory_bytes,
            "gpu_required": self.gpu_required,
            **({"node_ids": list(self.node_ids)} if self.node_ids else {}),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkRequirements":
        return cls(
            architectures=tuple(str(item) for item in value.get("architectures") or ()),
            operating_systems=tuple(
                str(item) for item in value.get("operating_systems") or ()
            ),
            capabilities=tuple(str(item) for item in value.get("capabilities") or ()),
            minimum_memory_bytes=int(value.get("minimum_memory_bytes") or 0),
            gpu_required=bool(value.get("gpu_required", False)),
            node_ids=tuple(str(item) for item in value.get("node_ids") or ()),
        )


@dataclass(frozen=True)
class WorkExecutionPolicy:
    retry_disabled: bool = True
    delivery: str = "at_most_once"
    require_receipt: bool = True
    require_effect_verification: bool = False

    def __post_init__(self) -> None:
        if self.delivery not in {"at_most_once", "idempotent"}:
            raise DistributedWorkError("unsupported Work delivery policy")

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_disabled": self.retry_disabled,
            "delivery": self.delivery,
            "require_receipt": self.require_receipt,
            **(
                {"require_effect_verification": True}
                if self.require_effect_verification
                else {}
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkExecutionPolicy":
        return cls(
            retry_disabled=bool(value.get("retry_disabled", True)),
            delivery=str(value.get("delivery") or "at_most_once"),
            require_receipt=bool(value.get("require_receipt", True)),
            require_effect_verification=bool(
                value.get("require_effect_verification", False)
            ),
        )


@dataclass(frozen=True)
class WorkAssignment:
    assignment_id: str
    work_id: str
    node_id: str
    assigned_at: str
    requirements: WorkRequirements
    input_artifacts: tuple[str, ...]
    execution_policy: WorkExecutionPolicy

    @classmethod
    def create(
        cls,
        *,
        work_id: str,
        node_id: str,
        requirements: WorkRequirements,
        input_artifacts: tuple[str, ...],
        execution_policy: WorkExecutionPolicy,
    ) -> "WorkAssignment":
        if not node_id.strip():
            raise DistributedWorkError("Work assignment requires a node")
        return cls(
            assignment_id=f"assignment_{uuid.uuid4().hex}",
            work_id=work_id,
            node_id=node_id.strip(),
            assigned_at=_timestamp(),
            requirements=requirements,
            input_artifacts=input_artifacts,
            execution_policy=execution_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "apeir.work-assignment/v1",
            "assignment_id": self.assignment_id,
            "work_id": self.work_id,
            "node_id": self.node_id,
            "assigned_at": self.assigned_at,
            "requirements": self.requirements.to_dict(),
            "input_artifacts": list(self.input_artifacts),
            "execution_policy": self.execution_policy.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkAssignment":
        if value.get("schema") != "apeir.work-assignment/v1":
            raise DistributedWorkError("Work assignment schema is invalid")
        assignment = cls(
            assignment_id=str(value.get("assignment_id") or ""),
            work_id=str(value.get("work_id") or ""),
            node_id=str(value.get("node_id") or ""),
            assigned_at=str(value.get("assigned_at") or ""),
            requirements=WorkRequirements.from_dict(
                _mapping(value.get("requirements"), "assignment requirements")
            ),
            input_artifacts=tuple(
                str(item) for item in value.get("input_artifacts") or ()
            ),
            execution_policy=WorkExecutionPolicy.from_dict(
                _mapping(value.get("execution_policy"), "assignment policy")
            ),
        )
        if not all(
            (
                assignment.assignment_id,
                assignment.work_id,
                assignment.node_id,
                assignment.assigned_at,
            )
        ):
            raise DistributedWorkError("Work assignment is incomplete")
        _artifact_references(assignment.input_artifacts)
        return assignment


@dataclass
class DistributedWork:
    intent: str
    requirements: WorkRequirements = field(default_factory=WorkRequirements)
    input_artifacts: tuple[str, ...] = ()
    execution_policy: WorkExecutionPolicy = field(default_factory=WorkExecutionPolicy)
    execution_capability: str = ""
    execution_arguments: dict[str, Any] = field(default_factory=dict)
    creator: str = ""
    priority: int = 0
    work_id: str = field(default_factory=lambda: f"work_{uuid.uuid4().hex}")
    state: DistributedWorkState = DistributedWorkState.CREATED
    assigned_node: str = ""
    output_artifacts: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    placement_decision: dict[str, Any] = field(default_factory=dict)
    assignment: WorkAssignment | None = None
    dispatch_record: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    state_history: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)
    target_resource_id: str = ""
    expected_effect: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    effect_verification: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.intent = self.intent.strip()
        self.creator = self.creator.strip()
        self.execution_capability = self.execution_capability.strip().lower()
        if not isinstance(self.execution_arguments, dict):
            raise DistributedWorkError("Work execution arguments must be an object")
        if not isinstance(self.expected_effect, dict):
            raise DistributedWorkError("Work expected effect must be an object")
        if not isinstance(self.provenance, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.provenance.items()
        ):
            raise DistributedWorkError("Work provenance must contain string fields")
        if not self.intent:
            raise DistributedWorkError("Work intent is required")
        if not self.work_id.strip():
            raise DistributedWorkError("Work id is required")
        if not 0 <= self.priority <= 100:
            raise DistributedWorkError("Work priority must be between 0 and 100")
        self.input_artifacts = _artifact_references(self.input_artifacts)
        self.output_artifacts = _artifact_references(self.output_artifacts)
        self.evidence_refs = _artifact_references(self.evidence_refs)
        if not self.state_history:
            self.state_history.append(
                {
                    "state": self.state.value,
                    "at": self.created_at,
                    "reason": "Work created",
                }
            )

    @property
    def terminal(self) -> bool:
        return self.state is DistributedWorkState.COMMITTED

    def transition(
        self,
        target: DistributedWorkState,
        *,
        reason: str,
        assigned_node: str = "",
    ) -> None:
        reason = reason.strip()
        if not reason:
            raise DistributedWorkError("Work transition reason is required")
        if target not in _TRANSITIONS[self.state]:
            raise DistributedWorkError(
                f"invalid Work transition: {self.state.value} -> {target.value}"
            )
        if (
            target is DistributedWorkState.COMMITTED
            and self.execution_policy.require_effect_verification
        ):
            if self.effect_verification.get("verdict") != "MATCH":
                raise DistributedWorkError(
                    "Reality Work commit requires an independent MATCH"
                )
        if target in {
            DistributedWorkState.ASSIGNED,
            DistributedWorkState.RUNNING,
        } and not (assigned_node or self.assigned_node):
            raise DistributedWorkError(f"{target.value} Work requires an assigned node")
        if target is DistributedWorkState.ASSIGNED:
            self.assigned_node = assigned_node.strip()
            if self.assignment is None:
                self.assignment = WorkAssignment.create(
                    work_id=self.work_id,
                    node_id=self.assigned_node,
                    requirements=self.requirements,
                    input_artifacts=self.input_artifacts,
                    execution_policy=self.execution_policy,
                )
            elif self.assignment.node_id != self.assigned_node:
                raise DistributedWorkError("Work assignment node binding changed")
        elif assigned_node and assigned_node != self.assigned_node:
            raise DistributedWorkError(
                "Work cannot change its assigned node implicitly"
            )
        now = _timestamp()
        self.state = target
        self.updated_at = now
        self.state_history.append({"state": target.value, "at": now, "reason": reason})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": WORK_SCHEMA,
            "work_id": self.work_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "creator": self.creator,
            "priority": self.priority,
            "intent": self.intent,
            "requirements": self.requirements.to_dict(),
            "input_artifacts": list(self.input_artifacts),
            "execution_policy": self.execution_policy.to_dict(),
            "execution_capability": self.execution_capability,
            "execution_arguments": dict(self.execution_arguments),
            "target_resource_id": self.target_resource_id,
            "expected_effect": dict(self.expected_effect),
            "provenance": dict(self.provenance),
            "state": self.state.value,
            "assigned_node": self.assigned_node,
            "output_artifacts": list(self.output_artifacts),
            "evidence_refs": list(self.evidence_refs),
            "placement_decision": dict(self.placement_decision),
            "assignment": self.assignment.to_dict() if self.assignment else None,
            "dispatch_record": dict(self.dispatch_record),
            "result_summary": dict(self.result_summary),
            "effect_verification": dict(self.effect_verification),
            "state_history": [dict(item) for item in self.state_history],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DistributedWork":
        if value.get("schema") != WORK_SCHEMA:
            raise DistributedWorkError("distributed Work schema is invalid")
        history = value.get("state_history")
        raw_assignment = value.get("assignment")
        if not isinstance(history, list) or not all(
            isinstance(item, Mapping) for item in history
        ):
            raise DistributedWorkError("distributed Work history is invalid")
        return cls(
            intent=str(value.get("intent") or ""),
            requirements=WorkRequirements.from_dict(
                _mapping(value.get("requirements"), "Work requirements")
            ),
            input_artifacts=tuple(
                str(item) for item in value.get("input_artifacts") or ()
            ),
            execution_policy=WorkExecutionPolicy.from_dict(
                _mapping(value.get("execution_policy"), "Work execution policy")
            ),
            execution_capability=str(value.get("execution_capability") or ""),
            execution_arguments=dict(value.get("execution_arguments") or {}),
            target_resource_id=str(value.get("target_resource_id") or ""),
            expected_effect=dict(value.get("expected_effect") or {}),
            provenance={
                str(key): str(item)
                for key, item in dict(value.get("provenance") or {}).items()
            },
            creator=str(value.get("creator") or ""),
            priority=int(value.get("priority") or 0),
            work_id=str(value.get("work_id") or ""),
            state=DistributedWorkState(str(value.get("state") or "")),
            assigned_node=str(value.get("assigned_node") or ""),
            output_artifacts=tuple(
                str(item) for item in value.get("output_artifacts") or ()
            ),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs") or ()),
            placement_decision=dict(value.get("placement_decision") or {}),
            assignment=(
                WorkAssignment.from_dict(raw_assignment)
                if isinstance(raw_assignment, Mapping)
                else None
            ),
            dispatch_record=dict(value.get("dispatch_record") or {}),
            result_summary=dict(value.get("result_summary") or {}),
            effect_verification=dict(value.get("effect_verification") or {}),
            state_history=[
                {str(key): str(item_value) for key, item_value in item.items()}
                for item in history
            ],
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
        )


class DistributedWorkStore:
    """Atomic local persistence for Controller-owned distributed Works."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.expanduser().resolve()
        self.path = self.state_dir / "distributed-works.json"
        self.lock_path = self.state_dir / "distributed-works.lock"
        with file_lock(self.lock_path):
            self._works = self._load()

    def create(self, work: DistributedWork) -> DistributedWork:
        with file_lock(self.lock_path):
            self._works = self._load()
            if work.work_id in self._works:
                raise DistributedWorkError(f"Work already exists: {work.work_id}")
            staged = dict(self._works)
            staged[work.work_id] = DistributedWork.from_dict(work.to_dict())
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(work.to_dict())

    def get(self, work_id: str) -> DistributedWork | None:
        with file_lock(self.lock_path):
            return self._get_locked(work_id)

    def _get_locked(self, work_id: str) -> DistributedWork | None:
        """Read while the caller holds the canonical store lock."""
        self._works = self._load()
        value = self._works.get(work_id)
        return DistributedWork.from_dict(value.to_dict()) if value else None

    def list(self) -> list[DistributedWork]:
        with file_lock(self.lock_path):
            self._works = self._load()
            return [
                DistributedWork.from_dict(self._works[key].to_dict())
                for key in sorted(self._works)
            ]

    def transition(
        self,
        work_id: str,
        target: DistributedWorkState,
        *,
        reason: str,
        assigned_node: str = "",
    ) -> DistributedWork:
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            current.transition(target, reason=reason, assigned_node=assigned_node)
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def record_placement(
        self, work_id: str, decision: Mapping[str, Any]
    ) -> DistributedWork:
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            if current.state is not DistributedWorkState.SCHEDULED:
                raise DistributedWorkError("placement requires a SCHEDULED Work")
            if (
                decision.get("schema") != "apeir.work-placement/v1"
                or decision.get("authority") != "placement-only"
                or decision.get("grants_capabilities") is not False
            ):
                raise DistributedWorkError("Work placement decision is invalid")
            current.placement_decision = dict(decision)
            current.updated_at = _timestamp()
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def assign(self, work_id: str, node_id: str) -> DistributedWork:
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            if current.state is not DistributedWorkState.SCHEDULED:
                raise DistributedWorkError("assignment requires a SCHEDULED Work")
            current.transition(
                DistributedWorkState.ASSIGNED,
                reason="Deterministic capability and resource match",
                assigned_node=node_id,
            )
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def record_dispatch(
        self, work_id: str, dispatch: Mapping[str, Any]
    ) -> DistributedWork:
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            if (
                current.state is not DistributedWorkState.ASSIGNED
                or not current.assignment
            ):
                raise DistributedWorkError("dispatch requires an ASSIGNED Work")
            if (
                dispatch.get("schema") != "apeir.work-dispatch/v1"
                or dispatch.get("work_id") != work_id
                or dispatch.get("assignment_id") != current.assignment.assignment_id
                or dispatch.get("node_id") != current.assigned_node
            ):
                raise DistributedWorkError("Work dispatch record is invalid")
            if current.dispatch_record:
                if current.dispatch_record != dict(dispatch):
                    raise DistributedWorkError("Work dispatch binding changed")
                return current
            current.dispatch_record = dict(dispatch)
            current.updated_at = _timestamp()
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def record_result(
        self,
        work_id: str,
        result: Mapping[str, Any],
        *,
        output_artifacts: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> DistributedWork:
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            if result.get("schema") != "apeir.work-result-summary/v1":
                raise DistributedWorkError("Work result summary is invalid")
            if current.result_summary:
                if current.result_summary != dict(result):
                    raise DistributedWorkError("Work result binding changed")
                return current
            current.result_summary = dict(result)
            current.output_artifacts = _artifact_references(output_artifacts)
            current.evidence_refs = _artifact_references(evidence_refs)
            current.updated_at = _timestamp()
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def record_effect_verification(
        self,
        work_id: str,
        verification: Mapping[str, Any],
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> DistributedWork:
        """Persist the independent Reality verdict before any effect commit."""
        with file_lock(self.lock_path):
            current = self._get_locked(work_id)
            if current is None:
                raise DistributedWorkError(f"Work does not exist: {work_id}")
            if current.state is not DistributedWorkState.VERIFIED:
                raise DistributedWorkError(
                    "effect verification requires receipt-VERIFIED Work"
                )
            value = dict(verification)
            receipt_digest = hashlib.sha256(
                json.dumps(
                    current.result_summary.get("remote_execution_receipt") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if (
                value.get("operation_id") != work_id
                or value.get("receipt_operation_id") != work_id
                or value.get("device_id") != current.target_resource_id
                or value.get("receipt_digest") != receipt_digest
                or not value.get("observation_ids")
                or not evidence_refs
            ):
                raise DistributedWorkError(
                    "effect verification provenance is incomplete or changed"
                )
            if value.get("work_id") != work_id or value.get("verdict") not in {
                "MATCH",
                "MISMATCH",
                "UNKNOWN",
            }:
                raise DistributedWorkError("effect verification binding is invalid")
            if current.effect_verification:
                if current.effect_verification == value:
                    return current
                if current.effect_verification.get("verdict") == "MATCH":
                    raise DistributedWorkError(
                        "committable effect verification binding changed"
                    )
            current.effect_verification = value
            current.evidence_refs = _artifact_references(
                (*current.evidence_refs, *evidence_refs)
            )
            current.updated_at = _timestamp()
            staged = dict(self._works)
            staged[work_id] = current
            self._save(staged)
            self._works = staged
        return DistributedWork.from_dict(current.to_dict())

    def counts(self) -> dict[str, int]:
        with file_lock(self.lock_path):
            self._works = self._load()
            return {
                state.value: sum(work.state is state for work in self._works.values())
                for state in DistributedWorkState
                if any(work.state is state for work in self._works.values())
            }

    def _load(self) -> dict[str, DistributedWork]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DistributedWorkError("distributed Work store is unreadable") from exc
        if value.get("schema") != WORK_STORE_SCHEMA or not isinstance(
            value.get("works"), dict
        ):
            raise DistributedWorkError("distributed Work store is invalid")
        works: dict[str, DistributedWork] = {}
        for work_id, item in value["works"].items():
            if not isinstance(item, Mapping):
                raise DistributedWorkError("distributed Work entry is invalid")
            work = DistributedWork.from_dict(item)
            if work.work_id != work_id:
                raise DistributedWorkError("distributed Work id binding is invalid")
            works[work_id] = work
        return works

    def _save(self, works: Mapping[str, DistributedWork]) -> None:
        from nous_runtime.core.redaction import redact_sensitive_data

        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema": WORK_STORE_SCHEMA,
                        "works": {
                            key: redact_sensitive_data(works[key].to_dict())
                            for key in sorted(works)
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            restrict_owner_only_file(temporary, subject="distributed Work state")
            _replace_file(temporary, self.path)
            restrict_owner_only_file(self.path, subject="distributed Work state")
        finally:
            temporary.unlink(missing_ok=True)


def _replace_file(source: Path, target: Path) -> None:
    """Bound Windows sharing violations without weakening atomic replacement."""
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.01 * (attempt + 1))


def _artifact_references(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
    if any(not item.startswith("artifact://") for item in normalized):
        raise DistributedWorkError("Work artifacts must use artifact:// references")
    return normalized


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DistributedWorkError(f"{label} must be an object")
    return value


__all__ = [
    "DistributedWork",
    "DistributedWorkError",
    "DistributedWorkState",
    "DistributedWorkStore",
    "WorkAssignment",
    "WorkExecutionPolicy",
    "WorkRequirements",
]
