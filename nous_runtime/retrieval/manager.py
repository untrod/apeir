"""Retrieval index rebuild and activation pipeline."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from nous_runtime.inspector.models import DiagnosticFinding
from nous_runtime.retrieval.exporter import RetrievalRecordExporter, content_revision, source_revision
from nous_runtime.retrieval.indexing import (
    IndexBuildOptions,
    IndexBuildResult,
    BackendBinding,
    IndexGeneration,
    IndexGenerationState,
    LogicalIndexSpec,
    RetrievalIndexVerification,
    new_generation_id,
)
from nous_runtime.retrieval.models import RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import IndexSpec
from nous_runtime.retrieval.registry import RetrievalBackendRegistry, registry
from nous_runtime.retrieval.store import IndexGenerationStore, JsonlIndexGenerationStore


class RetrievalIndexManager:
    def __init__(
        self,
        *,
        workspace_path: str | Path,
        backend_registry: RetrievalBackendRegistry = registry,
        store: IndexGenerationStore | None = None,
        exporter: RetrievalRecordExporter | None = None,
    ):
        self.workspace_path = Path(workspace_path)
        self.backend_registry = backend_registry
        self.store = store or JsonlIndexGenerationStore(self.workspace_path)
        self.exporter = exporter or RetrievalRecordExporter(self.workspace_path)

    def create_gateway(self, logical_index: str = "memory"):
        from nous_runtime.retrieval.gateway import RetrievalGateway

        return RetrievalGateway(
            backend_registry=self.backend_registry,
            generation_store=self.store,
            logical_index=logical_index,
        )
    def create_generation(self, spec: LogicalIndexSpec) -> IndexGeneration:
        generation = IndexGeneration(
            generation_id=new_generation_id(),
            logical_index=spec.logical_index,
            backend_id=spec.backend_id,
            workspace_id=spec.workspace_id,
            project_id=spec.project_id,
            state=IndexGenerationState.BUILDING,
            schema_version=spec.schema_version,
            metadata={"spec": spec.to_dict()},
        )
        self.store.append(generation)
        return generation

    def build_generation(
        self,
        generation_id: str,
        options: IndexBuildOptions | None = None,
    ) -> IndexBuildResult:
        options = options or IndexBuildOptions()
        generation = self._require_generation(generation_id)
        spec = LogicalIndexSpec.from_dict(generation.metadata.get("spec") or {})
        backend = self.backend_registry.resolve(generation.backend_id)
        backend.ensure_index(
            IndexSpec(
                name=generation.logical_index,
                record_types=spec.record_types,
                embedding_model=spec.embedding_model_id or "",
                distance_metric=spec.distance_metric or "cosine",
                metadata={
                    **spec.to_dict(),
                    "generation_id": generation.generation_id,
                    "workspace_id": spec.workspace_id,
                    "project_id": spec.project_id,
                },
            )
        )
        records = tuple(
            self.exporter.export_all(
                workspace_id=spec.workspace_id,
                project_id=spec.project_id,
                record_types=spec.record_types or None,
                active_only=True,
            )
        )
        started = time.perf_counter()
        indexed = 0
        failed = 0
        batch_count = 0
        errors: list[str] = []
        for batch in _batches(records, options.batch_size):
            batch_count += 1
            try:
                result = backend.upsert(list(batch), generation_id=generation.generation_id)
            except Exception as exc:
                result = None
                errors.append(str(exc))
                failed += len(batch)
            if result is not None:
                indexed += int(result.count)
                for error in result.errors:
                    errors.append(str(error))
                if not result.ok:
                    failed += len(result.errors) or len(batch)
            if errors and (options.fail_fast or len(errors) > options.max_errors):
                break

        duration_ms = (time.perf_counter() - started) * 1000
        target_state = IndexGenerationState.SHADOW if failed == 0 else IndexGenerationState.FAILED
        updated = generation.with_build_result(
            state=target_state,
            record_count=len(records),
            content_hash=content_revision(records),
            source_revision=source_revision(records),
            verified=False,
            failure_reason="; ".join(errors[:3]) if failed else None,
            metadata_update={
                "backend_binding": BackendBinding(
                    backend_resource_id=_backend_resource_id(generation, spec),
                    backend_schema_hash=_schema_hash(spec),
                    embedding_model_id=spec.embedding_model_id,
                    dimension=spec.dimension,
                    distance_metric=spec.distance_metric,
                    record_count=indexed,
                    verification_hash=content_revision(records),
                ).to_dict()
            },
        )
        self.store.update(updated)
        if options.verify_after_build and failed == 0:
            verification = self.verify_generation(updated.generation_id, expected_records=records)
            if verification.valid:
                self.store.update_state(updated.generation_id, IndexGenerationState.SHADOW, verified=True)
        return IndexBuildResult(
            generation_id=generation_id,
            exported_records=len(records),
            indexed_records=indexed,
            skipped_records=max(0, len(records) - indexed - failed),
            failed_records=failed,
            batch_count=batch_count,
            duration_ms=duration_ms,
            errors=tuple(errors),
        )

    def verify_generation(
        self,
        generation_id: str,
        expected_records: tuple[RetrievalRecord, ...] | None = None,
    ) -> RetrievalIndexVerification:
        generation = self._require_generation(generation_id)
        spec = LogicalIndexSpec.from_dict(generation.metadata.get("spec") or {})
        backend = self.backend_registry.resolve(generation.backend_id)
        expected = expected_records or tuple(
            self.exporter.export_all(
                workspace_id=spec.workspace_id,
                project_id=spec.project_id,
                record_types=spec.record_types or None,
                active_only=True,
            )
        )
        expected_by_id = {r.record_id: r for r in expected}
        duplicate_ids = _duplicates([r.record_id for r in expected])
        scope = RetrievalScope(workspace_id=spec.workspace_id, project_ids=(spec.project_id,))
        backend_ids = set(backend.list_record_ids(generation_id, scope))
        records = getattr(backend, "records", {})
        scoped = {
            rid: record for rid, record in records.items()
            if rid in backend_ids
            and getattr(record, "workspace_id", "") == spec.workspace_id
            and getattr(record, "project_id", "") == spec.project_id
        } if isinstance(records, dict) else {}
        if not scoped and backend_ids and not isinstance(records, dict):
            scoped = {record_id: expected_by_id[record_id] for record_id in backend_ids if record_id in expected_by_id}
        missing = tuple(sorted(set(expected_by_id) - set(scoped)))
        orphan = tuple(sorted(set(scoped) - set(expected_by_id)))
        hash_mismatches = tuple(
            sorted(
                rid for rid, expected_record in expected_by_id.items()
                if rid in scoped and scoped[rid].content_hash != expected_record.content_hash
            )
        )
        findings = _verification_findings(generation_id, missing, orphan, duplicate_ids, hash_mismatches)
        valid = not missing and not orphan and not duplicate_ids and not hash_mismatches
        if valid:
            generation = self._require_generation(generation_id)
            if generation.state == IndexGenerationState.SHADOW:
                metadata = dict(generation.metadata)
                binding = dict(metadata.get("backend_binding") or {})
                binding["last_verified_at"] = _utc_now()
                binding["record_count"] = len(scoped)
                binding["verification_hash"] = content_revision(expected)
                self.store.update(generation.with_metadata({"backend_binding": binding}))
                self.store.update_state(generation_id, IndexGenerationState.SHADOW, verified=True)
        return RetrievalIndexVerification(
            generation_id=generation_id,
            valid=valid,
            expected_count=len(expected),
            actual_count=len(scoped),
            missing_record_ids=missing,
            orphan_record_ids=orphan,
            duplicate_record_ids=tuple(duplicate_ids),
            hash_mismatches=hash_mismatches,
            findings=tuple(findings),
        )

    def activate_generation(self, generation_id: str) -> IndexGeneration:
        generation = self._require_generation(generation_id)
        if generation.state != IndexGenerationState.SHADOW:
            raise ValueError("only shadow generations can be activated")
        if not generation.verified:
            raise ValueError("generation must be verified before activation")
        active = self.store.active(generation.logical_index, generation.workspace_id, generation.project_id)
        if active and active.generation_id != generation.generation_id:
            self.store.update_state(active.generation_id, IndexGenerationState.DRAINING)
        activated = self.store.update_state(generation.generation_id, IndexGenerationState.ACTIVE)
        if active and active.generation_id != generation.generation_id:
            self.store.update_state(active.generation_id, IndexGenerationState.RETIRED)
        return activated

    def retire_generation(self, generation_id: str) -> IndexGeneration:
        generation = self._require_generation(generation_id)
        if generation.state == IndexGenerationState.ACTIVE:
            generation = self.store.update_state(generation_id, IndexGenerationState.DRAINING)
        if generation.state in {IndexGenerationState.DRAINING, IndexGenerationState.FAILED, IndexGenerationState.SHADOW}:
            return self.store.update_state(generation_id, IndexGenerationState.RETIRED)
        return generation

    def rebuild(
        self,
        spec: LogicalIndexSpec,
        options: IndexBuildOptions | None = None,
        *,
        activate: bool = True,
    ) -> IndexBuildResult:
        generation = self.create_generation(spec)
        result = self.build_generation(generation.generation_id, options)
        if result.ok and activate:
            latest = self._require_generation(generation.generation_id)
            if latest.verified:
                self.activate_generation(latest.generation_id)
        return result

    def status(self, logical_index: str | None = None) -> list[IndexGeneration]:
        return self.store.list(logical_index)

    def _require_generation(self, generation_id: str) -> IndexGeneration:
        generation = self.store.get(generation_id)
        if generation is None:
            raise KeyError(f"generation not found: {generation_id}")
        return generation


def _batches(records: tuple[RetrievalRecord, ...], batch_size: int):
    for index in range(0, len(records), batch_size):
        yield records[index:index + batch_size]


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return sorted(dupes)


def _schema_hash(spec: LogicalIndexSpec) -> str:
    raw = json.dumps(spec.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _backend_resource_id(generation: IndexGeneration, spec: LogicalIndexSpec) -> str:
    return f"{generation.backend_id}:{spec.workspace_id}:{spec.logical_index}:{generation.generation_id}"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _verification_findings(
    generation_id: str,
    missing: tuple[str, ...],
    orphan: tuple[str, ...],
    duplicate_ids: list[str],
    hash_mismatches: tuple[str, ...],
) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []
    if missing:
        findings.append(
            DiagnosticFinding(
                code="INDEX_MISSING_RECORDS",
                severity="error",
                component="retrieval",
                message="Indexed backend is missing expected retrieval records.",
                remediation="Run `nous retrieval index rebuild`.",
                details={"generation_id": generation_id, "count": len(missing)},
            )
        )
    if orphan:
        findings.append(
            DiagnosticFinding(
                code="INDEX_ORPHAN_RECORDS",
                severity="warning",
                component="retrieval",
                message="Indexed backend contains records outside the expected generation.",
                remediation="Rebuild or compact the retrieval index.",
                details={"generation_id": generation_id, "count": len(orphan)},
            )
        )
    if duplicate_ids:
        findings.append(
            DiagnosticFinding(
                code="INDEX_DUPLICATE_RECORDS",
                severity="error",
                component="retrieval",
                message="Exporter produced duplicate retrieval record IDs.",
                remediation="Check source record identity mapping.",
                details={"generation_id": generation_id, "count": len(duplicate_ids)},
            )
        )
    if hash_mismatches:
        findings.append(
            DiagnosticFinding(
                code="INDEX_HASH_MISMATCH",
                severity="error",
                component="retrieval",
                message="Indexed record content hash does not match the canonical export.",
                remediation="Rebuild the retrieval index from canonical records.",
                details={"generation_id": generation_id, "count": len(hash_mismatches)},
            )
        )
    return findings
