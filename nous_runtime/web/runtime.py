"""Unified Web search/fetch facade over the governed network capability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.artifact.models import ArtifactType


CapabilityExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_MAX_MODEL_CONTENT = 256 * 1024
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set_cookie",
    "token",
    "secret",
    "password",
    "credential",
    "credential_ref",
}


class WebRuntime:
    """Normalize governed Web results and close them into immutable evidence."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        capability_executor: CapabilityExecutor | None = None,
    ) -> None:
        self.root = Path(workspace).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError("the active workspace does not exist")
        self._executor = capability_executor or self._execute_network_capability
        self._artifact_store: ContentAddressedArtifactStore | None = None

    def search(self, values: Mapping[str, Any]) -> dict[str, Any]:
        query = str(values.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        request = {
            "query": query,
            "max_results": max(1, min(int(values.get("max_results") or 10), 20)),
            "timeout_seconds": max(
                1, min(int(values.get("timeout_seconds") or 30), 120)
            ),
            "max_response_bytes": max(
                1, min(int(values.get("max_response_bytes") or 1_048_576), 5_242_880)
            ),
        }
        return self._run("search", request)

    def fetch(self, values: Mapping[str, Any]) -> dict[str, Any]:
        url = str(values.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url is required"}
        request = {
            "url": url,
            "method": "GET",
            "timeout_seconds": max(
                1, min(int(values.get("timeout_seconds") or 30), 120)
            ),
            "max_response_bytes": max(
                1, min(int(values.get("max_response_bytes") or 1_048_576), 5_242_880)
            ),
            "max_redirects": 5,
            "max_retries": max(0, min(int(values.get("max_retries") or 1), 2)),
        }
        return self._run("fetch", request)

    def _run(self, kind: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = dict(self._executor(request))
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "error_code": type(exc).__name__,
            }
        if not bool(raw.get("ok")):
            return {
                "ok": False,
                "error": str(
                    raw.get("error_message")
                    or raw.get("error")
                    or raw.get("error_code")
                    or "governed Web request failed"
                ),
                "error_code": str(raw.get("error_code") or "WEB_REQUEST_FAILED"),
                "request_id": str(raw.get("request_id") or ""),
                "run_id": str(raw.get("run_id") or ""),
            }

        evidence = {
            "schema": "apeir.web-evidence/v1",
            "kind": kind,
            "request": _redact(request),
            "result": _redact(raw),
            "content_policy": {
                "classification": "untrusted_external_content",
                "authority": "none",
                "model_content_limit_bytes": _MAX_MODEL_CONTENT,
            },
        }
        encoded = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            stored = self._store().store_bytes(
                encoded,
                artifact_type=ArtifactType.EVIDENCE,
                name=f"web-{kind}-{str(raw.get('request_id') or 'request')}.json",
                media_type="application/vnd.apeir.web-evidence+json",
                produced_by="apeir.web-runtime",
                metadata={
                    "evidence_schema": "apeir.web-evidence/v1",
                    "kind": kind,
                    "request_id": str(raw.get("request_id") or ""),
                    "run_id": str(raw.get("run_id") or ""),
                    "source_id": _source_id(raw),
                    "content_hash": _content_hash(raw),
                    "untrusted_external_content": True,
                    "authority": "none",
                },
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Web evidence could not be stored: {exc}",
                "error_code": "WEB_EVIDENCE_STORE_FAILED",
                "request_id": str(raw.get("request_id") or ""),
                "run_id": str(raw.get("run_id") or ""),
            }

        artifact = dict(stored["artifact"])
        return self._model_result(kind, raw, artifact)

    def _model_result(
        self, kind: str, raw: dict[str, Any], artifact: dict[str, Any]
    ) -> dict[str, Any]:
        base = {
            "ok": True,
            "kind": kind,
            "request_id": str(raw.get("request_id") or ""),
            "run_id": str(raw.get("run_id") or ""),
            "evidence_ref": {
                "artifact_ref": str(artifact["digest"]),
                "digest": str(artifact["digest"]),
                "media_type": str(artifact["media_type"]),
            },
            "untrusted_external_content": True,
            "authority": "none",
        }
        if kind == "search":
            evidence = raw.get("search_evidence")
            citation = (
                evidence.get("citation") if isinstance(evidence, Mapping) else None
            )
            return {
                **base,
                "query": str(raw.get("query") or ""),
                "results": [
                    _redact(dict(item))
                    for item in raw.get("results") or ()
                    if isinstance(item, Mapping)
                ],
                "citation": _redact(citation) if isinstance(citation, Mapping) else {},
            }
        content = str(raw.get("content") or "")
        model_content, content_truncated = _truncate_utf8(content, _MAX_MODEL_CONTENT)
        return {
            **base,
            "url": str(raw.get("final_url") or raw.get("url") or ""),
            "content": model_content,
            "content_truncated": content_truncated,
            "content_type": str(raw.get("content_type") or ""),
            "content_hash": str(raw.get("content_hash") or ""),
            "citation": _redact(raw.get("citation") or {}),
        }

    def _store(self) -> ContentAddressedArtifactStore:
        if self._artifact_store is None:
            self._artifact_store = ContentAddressedArtifactStore(
                self.root / ".nous" / "artifacts"
            )
        return self._artifact_store

    def _execute_network_capability(
        self, values: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        from nous_runtime.capability.resolver import execute_capability_observation

        observation = execute_capability_observation(
            "network.fetch",
            _governance_surface="work_harness",
            _workspace_root=str(self.root),
            **dict(values),
        )
        metadata = dict(observation.metadata or {})
        if observation.status != "success":
            return {
                "ok": False,
                "error": "; ".join(observation.errors) or "network capability failed",
                "error_code": str(
                    metadata.get("error_code") or "NETWORK_CAPABILITY_FAILED"
                ),
            }
        data = dict(observation.data or {})
        result = data.get("result", data)
        if not isinstance(result, Mapping):
            raise ValueError("network capability returned an invalid result")
        return dict(result)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("<REDACTED>" if _sensitive_key(str(key)) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _source_id(result: Mapping[str, Any]) -> str:
    if result.get("source_id"):
        return str(result["source_id"])
    evidence = result.get("search_evidence")
    return str(evidence.get("source_id") or "") if isinstance(evidence, Mapping) else ""


def _content_hash(result: Mapping[str, Any]) -> str:
    if result.get("content_hash"):
        return str(result["content_hash"])
    evidence = result.get("search_evidence")
    return (
        str(evidence.get("content_hash") or "") if isinstance(evidence, Mapping) else ""
    )


def _sensitive_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("token", "secret", "password", "credential", "cookie")
    )


def _truncate_utf8(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


__all__ = ["WebRuntime"]
