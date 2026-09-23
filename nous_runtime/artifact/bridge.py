"""Minimal stdio boundary exposing the Distribution Artifact Runtime to Kernel."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.artifact.models import ArtifactType

MAX_EVIDENCE_BYTES = 64 * 1024
REQUIRED_METADATA = frozenset(
    {
        "operation_id",
        "intent_id",
        "effect_id",
        "effect_contract_digest",
        "target_ref",
        "observer_identity",
        "node_identity",
        "evidence_schema",
        "observed_at",
    }
)


def handle_request(
    store: ContentAddressedArtifactStore, request: dict[str, Any]
) -> dict[str, Any]:
    operation = request.get("operation")
    if operation == "health":
        return {"ok": True, "schema": "nous.artifact-bridge/v1"}
    if operation == "put":
        encoded = request.get("content_base64")
        metadata = request.get("metadata")
        if not isinstance(encoded, str) or not isinstance(metadata, dict):
            raise ValueError("evidence PUT requires base64 content and metadata")
        missing = sorted(
            field
            for field in REQUIRED_METADATA
            if not isinstance(metadata.get(field), str) or not metadata[field]
        )
        if missing:
            raise ValueError("evidence metadata missing: " + ", ".join(missing))
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("evidence content is not valid base64") from exc
        if len(content) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence exceeds 65536 bytes")
        media_type = request.get("media_type")
        if not isinstance(media_type, str) or not media_type:
            raise ValueError("evidence media_type is required")
        result = store.store_bytes(
            content,
            artifact_type=ArtifactType.EVIDENCE,
            name=str(request.get("name") or f"effect-{metadata['effect_id']}.evidence"),
            media_type=media_type,
            produced_by=str(
                request.get("produced_by") or metadata["observer_identity"]
            ),
            metadata=metadata,
        )
        artifact = result["artifact"]
        digest = str(artifact["digest"])
        store.resolve(digest, verify=True)
        return {"ok": True, "artifact": artifact, "digest": digest}
    if operation in {"get", "stat"}:
        digest = request.get("digest")
        if not isinstance(digest, str):
            raise ValueError("evidence digest is required")
        record = store.get(digest)
        if record is None:
            raise ValueError("evidence artifact not found")
        path = store.resolve(digest, verify=True)
        response: dict[str, Any] = {
            "ok": True,
            "artifact": record.to_dict(),
            "digest": digest,
        }
        if operation == "get":
            content = path.read_bytes()
            if len(content) > MAX_EVIDENCE_BYTES:
                raise ValueError("evidence exceeds 65536 bytes")
            response["content_base64"] = base64.b64encode(content).decode("ascii")
        return response
    raise ValueError("unsupported artifact bridge operation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        request = json.loads(sys.stdin.buffer.read())
        if not isinstance(request, dict):
            raise ValueError("artifact bridge request must be an object")
        response = handle_request(ContentAddressedArtifactStore(args.root), request)
    except Exception as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
