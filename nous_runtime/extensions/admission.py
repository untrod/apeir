"""Fail-closed Runtime to Kernel extension admission pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nous_runtime.extensions.registry import ExtensionRegistry


class ExtensionAdmissionError(RuntimeError):
    pass


class KernelAdmissionClient(Protocol):
    async def admit_extension(
        self, admission: dict[str, Any], idempotency_key: str = ""
    ) -> dict[str, Any]: ...

    async def authorize_extension(
        self, authorization: dict[str, Any], idempotency_key: str = ""
    ) -> dict[str, Any]: ...

    async def revoke_extension(
        self, revocation: dict[str, Any], idempotency_key: str = ""
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    extension_id: str
    normalized_digest: str
    requested_capabilities: tuple[str, ...]
    granted_capabilities: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    approval_required: bool
    executor_constraints: dict[str, str]
    scope_constraints: dict[str, tuple[str, ...]]
    policy_version: str
    decision_reason: str
    receipt_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdmissionDecision":
        required = {
            "admitted",
            "extension_id",
            "normalized_digest",
            "requested_capabilities",
            "granted_capabilities",
            "denied_capabilities",
            "approval_required",
            "executor_constraints",
            "scope_constraints",
            "policy_version",
            "decision_reason",
            "receipt_id",
        }
        missing = required - set(data)
        if missing:
            raise ExtensionAdmissionError(
                "Kernel admission decision is incomplete: " + ", ".join(sorted(missing))
            )
        return cls(
            admitted=bool(data["admitted"]),
            extension_id=str(data["extension_id"]),
            normalized_digest=str(data["normalized_digest"]),
            requested_capabilities=tuple(str(item) for item in data["requested_capabilities"]),
            granted_capabilities=tuple(str(item) for item in data["granted_capabilities"]),
            denied_capabilities=tuple(str(item) for item in data["denied_capabilities"]),
            approval_required=bool(data["approval_required"]),
            executor_constraints={
                str(key): str(value)
                for key, value in dict(data["executor_constraints"]).items()
            },
            scope_constraints={
                str(key): tuple(str(item) for item in value)
                for key, value in dict(data["scope_constraints"]).items()
            },
            policy_version=str(data["policy_version"]),
            decision_reason=str(data["decision_reason"]),
            receipt_id=str(data["receipt_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "extension_id": self.extension_id,
            "normalized_digest": self.normalized_digest,
            "requested_capabilities": list(self.requested_capabilities),
            "granted_capabilities": list(self.granted_capabilities),
            "denied_capabilities": list(self.denied_capabilities),
            "approval_required": self.approval_required,
            "executor_constraints": dict(self.executor_constraints),
            "scope_constraints": {
                key: list(value) for key, value in self.scope_constraints.items()
            },
            "policy_version": self.policy_version,
            "decision_reason": self.decision_reason,
            "receipt_id": self.receipt_id,
        }


class ExtensionAdmissionService:
    def __init__(
        self,
        registry: ExtensionRegistry,
        kernel: KernelAdmissionClient,
    ):
        self.registry = registry
        self.kernel = kernel

    async def admit(self, extension_id: str) -> AdmissionDecision:
        """Verify local state, submit to Kernel, validate response, and persist."""

        try:
            manifest = self.registry.verify(extension_id)
        except (OSError, ValueError) as exc:
            raise ExtensionAdmissionError(f"extension integrity check failed: {exc}") from exc
        assert manifest.provenance is not None
        request = self.registry.admission_request(extension_id)
        idempotency_key = (
            f"extension:{extension_id}:{manifest.provenance.digest}:admit"
        )
        try:
            raw = await self.kernel.admit_extension(request, idempotency_key)
        except Exception as exc:
            raise ExtensionAdmissionError(
                f"Kernel admission unavailable or denied: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ExtensionAdmissionError("Kernel returned an invalid admission response")
        decision = AdmissionDecision.from_dict(raw)
        requested = {item.capability for item in manifest.capabilities}
        if decision.extension_id != extension_id:
            raise ExtensionAdmissionError("Kernel decision extension identity mismatch")
        if decision.normalized_digest != manifest.provenance.digest:
            raise ExtensionAdmissionError("Kernel decision digest mismatch")
        if set(decision.requested_capabilities) != requested:
            raise ExtensionAdmissionError("Kernel decision changed requested capabilities")
        if not set(decision.granted_capabilities).issubset(requested):
            raise ExtensionAdmissionError("Kernel decision attempted to expand capability grant")
        if not set(decision.denied_capabilities).issubset(requested):
            raise ExtensionAdmissionError("Kernel decision contains unknown denied capability")
        if set(decision.granted_capabilities) & set(decision.denied_capabilities):
            raise ExtensionAdmissionError("Kernel decision grants and denies the same capability")
        if not decision.admitted:
            raise ExtensionAdmissionError(
                f"Kernel denied extension admission: {decision.decision_reason}"
            )
        self.registry.record_admission(extension_id, decision.to_dict())
        return decision

    async def authorize(
        self,
        extension_id: str,
        approved_capabilities: tuple[str, ...],
        approval_id: str,
    ) -> AdmissionDecision:
        try:
            manifest = self.registry.verify(extension_id)
            prior = self.registry.read_admission(extension_id)
        except (OSError, ValueError) as exc:
            raise ExtensionAdmissionError(f"extension integrity check failed: {exc}") from exc
        if not prior:
            raise ExtensionAdmissionError("extension has no Kernel admission decision")
        assert manifest.provenance is not None
        request = {
            "admission": self.registry.admission_request(extension_id),
            "admission_receipt_id": str(prior.get("receipt_id") or ""),
            "approval_id": approval_id,
            "approved_capabilities": list(approved_capabilities),
        }
        try:
            raw = await self.kernel.authorize_extension(
                request,
                f"extension:{extension_id}:{manifest.provenance.digest}:authorize:{approval_id}",
            )
        except Exception as exc:
            raise ExtensionAdmissionError(
                f"Kernel authorization unavailable or denied: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ExtensionAdmissionError("Kernel returned an invalid authorization response")
        decision = self._validate_decision(extension_id, manifest, raw)
        if not set(decision.granted_capabilities).issubset(
            set(approved_capabilities)
        ):
            raise ExtensionAdmissionError("Kernel grant exceeds approved capabilities")
        self.registry.record_admission(extension_id, decision.to_dict())
        return decision

    async def revoke(
        self, extension_id: str, *, reason: str = "user_requested"
    ) -> AdmissionDecision:
        try:
            manifest = self.registry.verify(extension_id)
            prior = self.registry.read_admission(extension_id)
        except (OSError, ValueError) as exc:
            raise ExtensionAdmissionError(f"extension integrity check failed: {exc}") from exc
        if not prior or not prior.get("granted_capabilities"):
            raise ExtensionAdmissionError("extension has no active Kernel authority")
        assert manifest.provenance is not None
        request = {
            "schema_version": 1,
            "extension_id": extension_id,
            "content_digest": manifest.provenance.digest,
            "authorization_receipt_id": str(prior.get("receipt_id") or ""),
            "reason": reason,
        }
        try:
            raw = await self.kernel.revoke_extension(
                request,
                f"extension:{extension_id}:{manifest.provenance.digest}:revoke",
            )
        except Exception as exc:
            raise ExtensionAdmissionError(
                f"Kernel revocation unavailable or denied: {exc}"
            ) from exc
        decision = self._validate_decision(extension_id, manifest, raw)
        if decision.granted_capabilities:
            raise ExtensionAdmissionError("Kernel revocation retained capability grants")
        self.registry.record_revocation(extension_id, decision.to_dict())
        return decision

    @staticmethod
    def _validate_decision(extension_id, manifest, raw) -> AdmissionDecision:
        decision = AdmissionDecision.from_dict(raw)
        assert manifest.provenance is not None
        requested = {item.capability for item in manifest.capabilities}
        if decision.extension_id != extension_id:
            raise ExtensionAdmissionError("Kernel decision extension identity mismatch")
        if decision.normalized_digest != manifest.provenance.digest:
            raise ExtensionAdmissionError("Kernel decision digest mismatch")
        if set(decision.requested_capabilities) != requested:
            raise ExtensionAdmissionError("Kernel decision changed requested capabilities")
        if not set(decision.granted_capabilities).issubset(requested):
            raise ExtensionAdmissionError("Kernel decision attempted to expand capability grant")
        if not set(decision.denied_capabilities).issubset(requested):
            raise ExtensionAdmissionError("Kernel decision contains unknown denied capability")
        if set(decision.granted_capabilities) & set(decision.denied_capabilities):
            raise ExtensionAdmissionError("Kernel decision grants and denies the same capability")
        if not decision.admitted:
            raise ExtensionAdmissionError(
                f"Kernel denied extension admission: {decision.decision_reason}"
            )
        return decision
