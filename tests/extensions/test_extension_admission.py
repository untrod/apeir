from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from compat.nki_client import NKIClient
from nous_runtime.extensions import ExtensionRegistry
from nous_runtime.extensions.admission import (
    ExtensionAdmissionError,
    ExtensionAdmissionService,
)


def install_skill(tmp_path: Path) -> tuple[ExtensionRegistry, str]:
    source = tmp_path / "admission-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: admission-skill\n"
        "description: Admission fixture.\n"
        "allowed-tools: Read\n"
        "---\n"
        "Read only when authorized.\n",
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(source)
    return registry, manifest.extension_id


def decision_for(request: dict, **overrides) -> dict:
    capabilities = [item["capability"] for item in request["capability_requests"]]
    value = {
        "admitted": True,
        "extension_id": request["extension_id"],
        "normalized_digest": request["content_digest"],
        "requested_capabilities": capabilities,
        "granted_capabilities": [],
        "denied_capabilities": [],
        "approval_required": bool(capabilities),
        "executor_constraints": {"authority": "none"},
        "scope_constraints": {
            item["capability"]: item["scope"]
            for item in request["capability_requests"]
        },
        "policy_version": "extension-admission-v1",
        "decision_reason": "capability_approval_required",
        "receipt_id": "admission-fixture",
    }
    value.update(overrides)
    return value


class FakeKernel:
    def __init__(self, mutate=None, error: Exception | None = None):
        self.mutate = mutate
        self.error = error
        self.calls = []

    async def admit_extension(self, admission, idempotency_key=""):
        self.calls.append((admission, idempotency_key))
        if self.error:
            raise self.error
        result = decision_for(admission)
        return self.mutate(result) if self.mutate else result


def test_runtime_submits_kernel_admission_and_persists_decision(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    kernel = FakeKernel()
    decision = asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    assert decision.admitted
    assert decision.approval_required
    assert len(kernel.calls) == 1
    request, key = kernel.calls[0]
    assert request["metadata"]["authority"] == "none"
    assert request["metadata"]["supply_chain_verified"] == "true"
    assert request["metadata"]["signature_status"] == "Unsigned"
    for field in (
        "normalized_ir_digest",
        "sbom_digest",
        "provenance_digest",
        "signature_digest",
    ):
        assert request["metadata"][field].startswith("sha256:")
    assert "instructions" not in json.dumps(request)
    assert request["content_digest"] in key
    record = registry.list()[0]
    assert record["state"] == "approval_required"
    assert record["admission_receipt"] == "admission-fixture"


def test_kernel_denial_is_fail_closed(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    kernel = FakeKernel(
        mutate=lambda result: {
            **result,
            "admitted": False,
            "decision_reason": "policy_denied",
        }
    )
    with pytest.raises(ExtensionAdmissionError, match="Kernel denied"):
        asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    assert registry.list()[0]["state"] == "installed"


def test_kernel_unavailable_blocks_admission(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    kernel = FakeKernel(error=ConnectionError("offline"))
    with pytest.raises(ExtensionAdmissionError, match="unavailable or denied"):
        asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    assert registry.list()[0]["authority"] == "none"


def test_runtime_cannot_expand_kernel_grant(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    kernel = FakeKernel(
        mutate=lambda result: {
            **result,
            "granted_capabilities": ["filesystem.write"],
        }
    )
    with pytest.raises(ExtensionAdmissionError, match="expand capability"):
        asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))


def test_digest_change_invalidates_admission_before_kernel_call(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    manifest = registry.get(extension_id)
    assert manifest and manifest.provenance
    package = (
        registry.objects
        / manifest.provenance.digest.removeprefix("sha256:")
        / "package"
        / "SKILL.md"
    )
    package.write_text(package.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    kernel = FakeKernel()
    with pytest.raises(ExtensionAdmissionError, match="content digest mismatch"):
        asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    assert not kernel.calls


def test_lockfile_tamper_blocks_admission(tmp_path: Path):
    registry, extension_id = install_skill(tmp_path)
    lock = json.loads(registry.lock_path.read_text(encoding="utf-8"))
    lock["extensions"][0]["digest"] = "sha256:" + "0" * 64
    registry.lock_path.write_text(json.dumps(lock), encoding="utf-8")
    kernel = FakeKernel()
    with pytest.raises(ExtensionAdmissionError, match="lock digest"):
        asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    assert not kernel.calls


def test_python_nki_client_exposes_admit_extension():
    client = NKIClient("mock://fixture")
    captured = {}

    async def fake_request(method, payload=None, idempotency_key=""):
        captured.update(
            method=method, payload=payload, idempotency_key=idempotency_key
        )
        return {"admitted": True}

    client._request = fake_request
    result = asyncio.run(
        client.admit_extension({"extension_id": "skills/x"}, "idem-1")
    )
    assert result == {"admitted": True}
    assert captured == {
        "method": "AdmitExtension",
        "payload": {"extension_id": "skills/x"},
        "idempotency_key": "idem-1",
    }


def test_python_nki_client_exposes_extension_execution_authorization():
    client = NKIClient("mock://fixture")
    captured = {}

    async def fake_request(method, payload=None, idempotency_key=""):
        captured.update(
            method=method, payload=payload, idempotency_key=idempotency_key
        )
        return {"allowed": True}

    client._request = fake_request
    execution = {"extension_id": "skills/x", "operation": "run"}
    result = asyncio.run(
        client.authorize_extension_execution(execution, "idem-execute")
    )
    assert result == {"allowed": True}
    assert captured == {
        "method": "AuthorizeExtensionExecution",
        "payload": execution,
        "idempotency_key": "idem-execute",
    }
