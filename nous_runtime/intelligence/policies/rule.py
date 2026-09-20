"""Restricted structured rule policy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nous_runtime.intelligence.models import (
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    RuntimeDecision,
    decision_id_for,
)


@dataclass(frozen=True)
class RulePolicy:
    policy_id: str
    version: str
    decision_type: str
    priority: int
    conditions: tuple[dict[str, Any], ...]
    action: dict[str, Any]
    reason_code: str = "POLICY_MATCH"
    reason_message: str = "Policy conditions matched."

    def matches(self, request: DecisionRequest) -> bool:
        if self.decision_type and request.decision_type.value != self.decision_type:
            return False
        data = {"task": {"id": request.task_id}, "context": request.context.to_dict()}
        return all(_eval_condition(data, condition) for condition in self.conditions)

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        selected = str(self.action.get("selected") or self.action.get("mode") or "enabled")
        alternatives = tuple(str(v) for v in self.action.get("alternatives") or ())
        confidence = float(self.action.get("confidence", 0.8))
        reason = DecisionReason(
            code=self.reason_code,
            message=self.reason_message,
            weight=confidence,
            evidence={"policy_id": self.policy_id, "matched_conditions": len(self.conditions)},
        )
        return RuntimeDecision(
            decision_id=decision_id_for(request, self.policy_id, selected),
            task_id=request.task_id,
            decision_type=request.decision_type,
            outcome=DecisionOutcome(
                selected=selected,
                alternatives=alternatives,
                confidence=confidence,
                metadata=dict(self.action),
            ),
            reasons=(reason,),
            policy_id=self.policy_id,
            policy_version=self.version,
            inputs_snapshot=request.to_dict(),
        )


def validate_condition(condition: dict[str, Any]) -> None:
    allowed = {"eq", "ne", "neq", "in", "not_in", "contains", "exists", "gt", "gte", "lt", "lte", "and", "or", "not"}
    if not isinstance(condition, dict):
        raise ValueError("condition must be an object")
    if condition.get("operator") not in allowed:
        raise ValueError(f"unsupported policy operator: {condition.get('operator')}")
    op = str(condition["operator"])
    if op in {"and", "or"}:
        children = condition.get("conditions")
        if not isinstance(children, list) or not children:
            raise ValueError(f"{op} condition requires non-empty conditions")
        for child in children:
            validate_condition(child)
        return
    if op == "not":
        child = condition.get("condition")
        if not isinstance(child, dict):
            raise ValueError("not condition requires a nested condition")
        validate_condition(child)
        return
    field = str(condition.get("field") or "")
    if not field:
        raise ValueError("condition field is required")
    if field.startswith("_") or ".__" in field or field.split(".")[0] not in {"task", "context"}:
        raise ValueError(f"unsupported policy field path: {field}")


def _eval_condition(data: dict[str, Any], condition: dict[str, Any]) -> bool:
    validate_condition(condition)
    op = str(condition["operator"])
    if op == "and":
        return all(_eval_condition(data, child) for child in condition.get("conditions") or ())
    if op == "or":
        return any(_eval_condition(data, child) for child in condition.get("conditions") or ())
    if op == "not":
        return not _eval_condition(data, condition.get("condition") or {})
    actual = _get_path(data, str(condition["field"]))
    expected = condition.get("value")
    if op == "eq":
        return actual == expected
    if op in {"ne", "neq"}:
        return actual != expected
    if op == "in":
        return actual in (expected or ())
    if op == "not_in":
        return actual not in (expected or ())
    if op == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if op == "exists":
        return actual is not None
    if op == "gt":
        return float(actual or 0) > float(expected)
    if op == "gte":
        return float(actual or 0) >= float(expected)
    if op == "lt":
        return float(actual or 0) < float(expected)
    if op == "lte":
        return float(actual or 0) <= float(expected)
    return False


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
