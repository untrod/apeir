from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nous_runtime.extensions.admission import (
    ExtensionAdmissionError,
    ExtensionAdmissionService,
)
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore


def write_skill(root: Path, *, version: str = "1.0.0", with_script: bool = False) -> None:
    root.mkdir(exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: permission-skill\n"
        "description: Permission fixture.\n"
        "allowed-tools: Read\n"
        f"metadata:\n  version: {version}\n"
        "---\n"
        "Imported instructions are data only.\n",
        encoding="utf-8",
    )
    if with_script:
        scripts = root / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "run.py").write_text("print(''fixture'')\n", encoding="utf-8")


def kernel_decision(request: dict, *, grants=(), receipt="admission-1") -> dict:
    capabilities = [item["capability"] for item in request["capability_requests"]]
    granted = list(grants)
    return {
        "admitted": True,
        "extension_id": request["extension_id"],
        "normalized_digest": request["content_digest"],
        "requested_capabilities": capabilities,
        "granted_capabilities": granted,
        "denied_capabilities": [item for item in capabilities if item not in granted],
        "approval_required": len(granted) != len(capabilities),
        "executor_constraints": {"authority": "kernel_grant" if granted else "none"},
        "scope_constraints": {
            item["capability"]: item["scope"]
            for item in request["capability_requests"]
        },
        "policy_version": "extension-admission-v1",
        "decision_reason": "authorized" if granted else "capability_approval_required",
        "receipt_id": receipt,
    }


class FakeKernel:
    def __init__(self):
        self.admission_calls = []
        self.authorization_calls = []
        self.revocation_calls = []
        self.authorization_error: Exception | None = None

    async def admit_extension(self, admission, idempotency_key=""):
        self.admission_calls.append((admission, idempotency_key))
        return kernel_decision(admission)

    async def authorize_extension(self, authorization, idempotency_key=""):
        self.authorization_calls.append((authorization, idempotency_key))
        if self.authorization_error:
            raise self.authorization_error
        return kernel_decision(
            authorization["admission"],
            grants=authorization["approved_capabilities"],
            receipt="authorization-1",
        )

    async def revoke_extension(self, revocation, idempotency_key=""):
        self.revocation_calls.append((revocation, idempotency_key))
        admission = self.admission_calls[-1][0]
        decision = kernel_decision(admission, receipt="revocation-1")
        decision["policy_version"] = "extension-revocation-v1"
        decision["decision_reason"] = "authority_revoked"
        return decision


def services(tmp_path: Path):
    registry = ExtensionRegistry(tmp_path / "registry")
    kernel = FakeKernel()
    admission = ExtensionAdmissionService(registry, kernel)
    broker = ApprovalBroker(GovernanceStore(tmp_path / "governance"))
    permissions = ExtensionPermissionService(registry, admission, broker)
    return registry, kernel, admission, permissions


def context() -> AuthorizationContext:
    return AuthorizationContext(
        subject_type="user",
        subject_id="local-user",
        authn_method="cli_os_user",
        authn_confidence=1.0,
        session_locality="local",
    )


def test_permission_approval_is_bound_to_digest_and_kernel_authorized(tmp_path: Path):
    registry, kernel, admission, permissions = services(tmp_path)
    source = tmp_path / "permission-skill"
    write_skill(source)
    extension_id = registry.install(source).extension_id
    asyncio.run(admission.admit(extension_id))

    diff, request = permissions.request(extension_id, context())
    assert diff.added == ("tool.invoke",)
    assert request is not None
    pending = registry.get_record(extension_id)["pending_permission_request"]
    assert pending["digest"] == registry.get_record(extension_id)["digest"]

    result = asyncio.run(
        permissions.approve(extension_id, request.request_id, "local-admin")
    )
    assert result.granted_capabilities == ("tool.invoke",)
    assert kernel.authorization_calls[0][0]["approval_id"].startswith("aprsp_")
    record = registry.get_record(extension_id)
    assert record["state"] == "authorized"
    assert record["authority"] == "kernel_grant"
    assert "pending_permission_request" not in record


def test_upgrade_only_requests_new_capabilities_and_does_not_inherit_them(
    tmp_path: Path,
):
    registry, _, admission, permissions = services(tmp_path)
    source = tmp_path / "permission-skill"
    write_skill(source)
    extension_id = registry.install(source).extension_id
    asyncio.run(admission.admit(extension_id))
    _, request = permissions.request(extension_id, context())
    asyncio.run(permissions.approve(extension_id, request.request_id, "local-admin"))

    write_skill(source, version="2.0.0", with_script=True)
    registry.install(source)
    asyncio.run(admission.admit(extension_id))
    diff = permissions.diff(extension_id)
    assert diff.previously_granted == ("tool.invoke",)
    assert diff.unchanged == ("tool.invoke",)
    assert diff.added == ("filesystem.read", "process.execute")
    assert registry.get_record(extension_id)["granted_capabilities"] == []


def test_kernel_authorization_failure_preserves_approved_request_for_retry(
    tmp_path: Path,
):
    registry, kernel, admission, permissions = services(tmp_path)
    source = tmp_path / "permission-skill"
    write_skill(source)
    extension_id = registry.install(source).extension_id
    asyncio.run(admission.admit(extension_id))
    _, request = permissions.request(extension_id, context())
    kernel.authorization_error = ConnectionError("offline")

    with pytest.raises(ExtensionAdmissionError, match="unavailable or denied"):
        asyncio.run(permissions.approve(extension_id, request.request_id, "local-admin"))
    pending = registry.get_record(extension_id)["pending_permission_request"]
    approval_id = pending["approval_id"]

    kernel.authorization_error = None
    result = asyncio.run(
        permissions.approve(extension_id, request.request_id, "local-admin")
    )
    assert result.receipt_id == "authorization-1"
    assert kernel.authorization_calls[-1][0]["approval_id"] == approval_id


def test_stale_digest_cannot_consume_permission_approval(tmp_path: Path):
    registry, _, admission, permissions = services(tmp_path)
    source = tmp_path / "permission-skill"
    write_skill(source)
    extension_id = registry.install(source).extension_id
    asyncio.run(admission.admit(extension_id))
    _, request = permissions.request(extension_id, context())

    write_skill(source, version="2.0.0", with_script=True)
    registry.install(source)
    with pytest.raises(ExtensionAdmissionError, match="not pending"):
        asyncio.run(permissions.approve(extension_id, request.request_id, "local-admin"))


def test_revocation_removes_local_authority_and_binds_kernel_receipt(tmp_path: Path):
    registry, kernel, admission, permissions = services(tmp_path)
    source = tmp_path / "permission-skill"
    write_skill(source)
    extension_id = registry.install(source).extension_id
    asyncio.run(admission.admit(extension_id))
    _, request = permissions.request(extension_id, context())
    asyncio.run(permissions.approve(extension_id, request.request_id, "local-admin"))

    revoked = asyncio.run(permissions.revoke(extension_id, reason="security_review"))

    assert revoked.granted_capabilities == ()
    request_body, idempotency_key = kernel.revocation_calls[0]
    assert request_body["authorization_receipt_id"] == "authorization-1"
    assert request_body["reason"] == "security_review"
    assert idempotency_key.endswith(":revoke")
    record = registry.get_record(extension_id)
    assert record["state"] == "revoked"
    assert record["authority"] == "none"
    assert record["granted_capabilities"] == []
