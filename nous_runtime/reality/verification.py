"""Bind an existing OperationReceipt and Observation to an expected effect."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from nous_runtime.planner.observation import Observation
from nous_runtime.reality.contracts import EffectVerdict, EffectVerification, Operation


class EffectVerifier:
    """Small deterministic comparator; UNKNOWN always remains fail-closed."""

    def verify(
        self,
        operation: Operation,
        receipt: Mapping[str, Any],
        observations: Sequence[Observation],
    ) -> EffectVerification:
        receipt_operation_id = str(receipt.get("operation_id") or "")
        observation_ids = tuple(
            dict.fromkeys(item.observation_id for item in observations)
        )
        if receipt_operation_id != operation.operation_id:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.MISMATCH,
                "receipt is bound to a different operation",
                receipt,
            )
        receipt_schema = str(receipt.get("schema") or "")
        if receipt.get("result") and receipt["result"] != "COMPLETED":
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "operation receipt is not successful",
                receipt,
            )
        projected_schema = receipt.get("schema_version")
        receipt_digest = str(
            receipt.get("effect_digest") or receipt.get("output_digest") or ""
        )
        if not receipt_digest or not (
            receipt_schema == "nous.operation-receipt/v1" or projected_schema == 1
        ):
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "operation receipt is incomplete or unsupported",
                receipt,
            )
        if not operation.expected_effect:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "operation has no machine-verifiable expected effect",
                receipt,
            )
        if not observations:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "no successful observation is available",
                receipt,
            )
        target_observations = [
            item
            for item in observations
            if str(item.metadata.get("device_id") or item.data.get("device_id") or "")
            == operation.target_resource_id
        ]
        if not target_observations:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "observations are not bound to the operation target",
                receipt,
            )
        unique: dict[str, Observation] = {}
        for item in target_observations:
            if (
                item.observation_id in unique
                and unique[item.observation_id].to_dict() != item.to_dict()
            ):
                return self._result(
                    operation,
                    receipt_operation_id,
                    observation_ids,
                    EffectVerdict.UNKNOWN,
                    "duplicate observation identity has conflicting content",
                    receipt,
                )
            unique.setdefault(item.observation_id, item)
        current = tuple(unique.values())[-1]
        if current.status != "success":
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "latest target observation failed",
                receipt,
            )
        if operation.observation_request_id and (
            current.metadata.get("acquisition_id") != operation.observation_request_id
            or current.metadata.get("last_operation_id") != operation.operation_id
            or current.metadata.get("state_revision", 0) < 1
        ):
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "observation is not a fresh post-operation acquisition",
                receipt,
            )
        if current.metadata.get("stale") is True:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "latest observation is explicitly stale",
                receipt,
            )
        observed_operation = str(current.metadata.get("last_operation_id") or "")
        if observed_operation and observed_operation != operation.operation_id:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "observation is not causally bound to the operation",
                receipt,
            )
        observed_state = current.data.get("state")
        if not isinstance(observed_state, Mapping):
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "observation does not contain structured state",
                receipt,
            )
        matches = _contains(observed_state, operation.expected_effect)
        return self._result(
            operation,
            receipt_operation_id,
            observation_ids,
            EffectVerdict.MATCH if matches else EffectVerdict.MISMATCH,
            "observed state matches expected effect"
            if matches
            else "observed state contradicts expected effect",
            receipt,
        )

    @staticmethod
    def _result(
        operation: Operation,
        receipt_operation_id: str,
        observation_ids: tuple[str, ...],
        verdict: EffectVerdict,
        reason: str,
        receipt: Mapping[str, Any],
    ) -> EffectVerification:
        receipt_digest = hashlib.sha256(
            json.dumps(
                dict(receipt),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return EffectVerification(
            operation_id=operation.operation_id,
            receipt_operation_id=receipt_operation_id,
            observation_ids=observation_ids,
            verdict=verdict,
            reason=reason,
            work_id=operation.work_id,
            device_id=operation.target_resource_id,
            receipt_digest=receipt_digest,
        )


def _contains(observed: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key not in observed:
            return False
        observed_value = observed[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(observed_value, Mapping) or not _contains(
                observed_value, expected_value
            ):
                return False
        elif observed_value != expected_value:
            return False
    return True


__all__ = ["EffectVerifier"]
