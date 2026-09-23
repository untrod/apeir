from __future__ import annotations

import base64
from pathlib import Path

import pytest

from nous_runtime.artifact.bridge import handle_request
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.core.errors import ArtifactError


def _metadata() -> dict[str, str]:
    return {
        "operation_id": "operation-1",
        "intent_id": "operation-1",
        "effect_id": "effect-1",
        "effect_contract_digest": "a" * 64,
        "target_ref": "node://arm64-lab/service/test-api",
        "observer_identity": "apeir.http-service-observer",
        "node_identity": "node-arm64",
        "evidence_schema": "apeir.http-observation/v1",
        "observed_at": "2026-09-23T00:00:00Z",
    }


def test_bridge_put_get_uses_existing_verified_artifact_runtime(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    payload = b'{"http_status":200,"version":"B"}'
    stored = handle_request(
        store,
        {
            "operation": "put",
            "content_base64": base64.b64encode(payload).decode("ascii"),
            "media_type": "application/vnd.apeir.effect.http-observation+json",
            "metadata": _metadata(),
        },
    )
    digest = stored["digest"]
    assert stored["artifact"]["artifact_type"] == "evidence"
    assert stored["artifact"]["metadata"] == _metadata()
    fetched = handle_request(store, {"operation": "get", "digest": digest})
    assert base64.b64decode(fetched["content_base64"]) == payload


def test_bridge_missing_or_tampered_evidence_fails_closed(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="not found"):
        handle_request(store, {"operation": "get", "digest": "sha256:" + "0" * 64})
    stored = handle_request(
        store,
        {
            "operation": "put",
            "content_base64": base64.b64encode(b"trusted").decode("ascii"),
            "media_type": "application/octet-stream",
            "metadata": _metadata(),
        },
    )
    store.resolve(stored["digest"], verify=False).write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="integrity verification failed"):
        handle_request(store, {"operation": "get", "digest": stored["digest"]})
