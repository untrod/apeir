"""Workspace policy loading and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from nous_runtime.intelligence.models import DecisionType
from nous_runtime.intelligence.policies import RulePolicy, StaticPolicy
from nous_runtime.intelligence.policies.base import Policy
from nous_runtime.intelligence.policies.rule import validate_condition
from nous_runtime.intelligence.registry import PolicyRegistry


from nous_runtime.schema_registry import POLICY_SCHEMA_VERSION
POLICY_SOURCE_ORDER = {
    "system.default": 0,
    "runtime.global": 10,
    "user": 20,
    "workspace": 30,
    "project": 40,
    "task": 50,
    "explicit.override": 60,
}


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    policy_type: str
    decision_type: str
    version: str = "1.0"
    enabled: bool = True
    priority: int = 0
    conditions: tuple[dict[str, Any], ...] = ()
    constraints: tuple[dict[str, Any], ...] = ()
    weights: dict[str, float] = field(default_factory=dict)
    actions: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "workspace"
    source_path: str = ""
    schema_version: str = POLICY_SCHEMA_VERSION

    @property
    def policy_hash(self) -> str:
        return stable_policy_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["conditions"] = [dict(item) for item in self.conditions]
        data["constraints"] = [dict(item) for item in self.constraints]
        if include_hash:
            data["policy_hash"] = self.policy_hash
        return data

    def to_policy(self) -> Policy:
        if self.policy_type == "rule":
            return RulePolicy(
                policy_id=self.policy_id,
                version=self.version,
                decision_type=self.decision_type,
                priority=_effective_priority(self),
                conditions=self.conditions,
                action=self.actions,
                reason_code=str(self.metadata.get("reason_code") or "POLICY_MATCH"),
                reason_message=str(self.metadata.get("reason_message") or "Policy conditions matched."),
            )
        if self.policy_type == "static":
            return StaticPolicy(
                policy_id=self.policy_id,
                version=self.version,
                decision_type=self.decision_type,
                selected=str(self.actions.get("selected") or self.actions.get("mode") or "default"),
                priority=_effective_priority(self),
                confidence=float(self.actions.get("confidence", 0.5)),
                metadata={**dict(self.metadata), "policy_hash": self.policy_hash, "source": self.source},
            )
        raise PolicyValidationError(f"unsupported policy_type: {self.policy_type}")


@dataclass(frozen=True)
class PolicyDiagnostic:
    code: str
    severity: str
    message: str
    policy_id: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyLoadResult:
    registry: PolicyRegistry
    specs: tuple[PolicySpec, ...]
    diagnostics: tuple[PolicyDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policies": [spec.to_dict() for spec in self.specs],
            "diagnostics": [diag.to_dict() for diag in self.diagnostics],
        }


class PolicyLoadError(Exception):
    pass


class PolicyValidationError(Exception):
    pass


def load_workspace_policies(workspace_path: str | Path | None) -> PolicyLoadResult:
    registry = PolicyRegistry()
    diagnostics: list[PolicyDiagnostic] = []
    specs: list[PolicySpec] = []
    if workspace_path is None:
        return PolicyLoadResult(registry, tuple(), tuple())
    policy_dir = Path(workspace_path) / "policies"
    if not policy_dir.is_dir():
        return PolicyLoadResult(registry, tuple(), tuple())
    seen: dict[str, str] = {}
    for path in sorted(policy_dir.glob("*")):
        if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            raw = _load_structured_file(path)
            for item in _policy_items(raw):
                spec = parse_policy_spec(item, source_path=str(path))
                validate_policy_spec(spec)
                if spec.policy_id in seen:
                    diagnostics.append(
                        PolicyDiagnostic(
                            "POLICY_DUPLICATE_ID",
                            "error",
                            f"Duplicate policy id also defined in {seen[spec.policy_id]}",
                            spec.policy_id,
                            str(path),
                        )
                    )
                    continue
                seen[spec.policy_id] = str(path)
                if not spec.enabled:
                    diagnostics.append(
                        PolicyDiagnostic("POLICY_DISABLED", "info", "Policy is disabled.", spec.policy_id, str(path))
                    )
                    continue
                registry.register(
                    spec.to_policy(),
                    metadata={
                        "policy_hash": spec.policy_hash,
                        "source": spec.source,
                        "source_path": spec.source_path,
                        "schema_version": spec.schema_version,
                    },
                )
                specs.append(spec)
        except (PolicyLoadError, PolicyValidationError, ValueError) as exc:
            diagnostics.append(PolicyDiagnostic("POLICY_INVALID", "error", str(exc), source_path=str(path)))
    return PolicyLoadResult(registry, tuple(specs), tuple(diagnostics))


def parse_policy_spec(data: dict[str, Any], *, source_path: str = "") -> PolicySpec:
    if not isinstance(data, dict):
        raise PolicyValidationError("policy spec must be an object")
    return PolicySpec(
        policy_id=str(data.get("policy_id") or ""),
        policy_type=str(data.get("policy_type") or data.get("type") or "rule"),
        decision_type=str(data.get("decision_type") or ""),
        version=str(data.get("version") or "1.0"),
        enabled=bool(data.get("enabled", True)),
        priority=int(data.get("priority") or 0),
        conditions=tuple(dict(item) for item in data.get("conditions") or ()),
        constraints=tuple(dict(item) for item in data.get("constraints") or ()),
        weights={str(k): float(v) for k, v in dict(data.get("weights") or {}).items()},
        actions=dict(data.get("actions") or data.get("action") or {}),
        fallback=dict(data.get("fallback") or {}),
        metadata=dict(data.get("metadata") or {}),
        source=str(data.get("source") or _source_from_path(source_path)),
        source_path=source_path,
        schema_version=str(data.get("schema_version") or POLICY_SCHEMA_VERSION),
    )


def validate_policy_spec(spec: PolicySpec) -> None:
    if not spec.policy_id:
        raise PolicyValidationError("policy_id is required")
    if spec.policy_type not in {"rule", "static"}:
        raise PolicyValidationError(f"unsupported policy_type: {spec.policy_type}")
    try:
        DecisionType(spec.decision_type)
    except ValueError as exc:
        raise PolicyValidationError(f"unsupported decision_type: {spec.decision_type}") from exc
    if spec.schema_version != POLICY_SCHEMA_VERSION:
        raise PolicyValidationError(f"unsupported policy schema version: {spec.schema_version}")
    if spec.source not in POLICY_SOURCE_ORDER:
        raise PolicyValidationError(f"unsupported policy source: {spec.source}")
    for condition in spec.conditions:
        validate_condition(condition)


def stable_policy_hash(data: dict[str, Any]) -> str:
    normalized = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _effective_priority(spec: PolicySpec) -> int:
    return POLICY_SOURCE_ORDER[spec.source] * 10_000 + spec.priority


def _policy_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("policies"), list):
        return [dict(item) for item in raw["policies"]]
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [dict(item) for item in raw]
    raise PolicyValidationError("policy file must contain an object or list")


def _load_structured_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        import yaml

        return yaml.safe_load(text) or {}
    except Exception as exc:
        raise PolicyLoadError(f"failed to load policy file: {exc}") from exc


def _source_from_path(path: str) -> str:
    name = Path(path).stem.lower()
    if "override" in name:
        return "explicit.override"
    if "project" in name:
        return "project"
    if "task" in name:
        return "task"
    if "runtime" in name:
        return "runtime.global"
    if "user" in name:
        return "user"
    return "workspace"
