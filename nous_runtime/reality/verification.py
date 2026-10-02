"""Bind an existing OperationReceipt and Observation to an expected effect."""

from __future__ import annotations

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
        observation_ids = tuple(item.observation_id for item in observations)
        if receipt_operation_id != operation.operation_id:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.MISMATCH,
                "receipt is bound to a different operation",
            )
        receipt_schema = str(receipt.get("schema") or "")
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
            )
        if not operation.expected_effect:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "operation has no machine-verifiable expected effect",
            )
        successful = [item for item in observations if item.status == "success"]
        if not successful:
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "no successful observation is available",
            )
        target_observations = [
            item
            for item in successful
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
            )
        observed_state = target_observations[-1].data.get("state")
        if not isinstance(observed_state, Mapping):
            return self._result(
                operation,
                receipt_operation_id,
                observation_ids,
                EffectVerdict.UNKNOWN,
                "observation does not contain structured state",
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
        )

    @staticmethod
    def _result(
        operation: Operation,
        receipt_operation_id: str,
        observation_ids: tuple[str, ...],
        verdict: EffectVerdict,
        reason: str,
    ) -> EffectVerification:
        return EffectVerification(
            operation_id=operation.operation_id,
            receipt_operation_id=receipt_operation_id,
            observation_ids=observation_ids,
            verdict=verdict,
            reason=reason,
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
