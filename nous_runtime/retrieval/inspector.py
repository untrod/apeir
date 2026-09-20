"""Read-only retrieval inspector helpers."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from nous_runtime.inspector.models import DiagnosticFinding
from nous_runtime.retrieval.embeddings import embedding_registry
from nous_runtime.retrieval.indexing import IndexGenerationState
from nous_runtime.retrieval.jobs import JsonlIndexingOutbox
from nous_runtime.retrieval.registry import registry
from nous_runtime.retrieval.store import JsonlIndexGenerationStore


def retrieval_snapshot(workspace_path: str | Path) -> dict:
    store = JsonlIndexGenerationStore(workspace_path)
    outbox = JsonlIndexingOutbox(workspace_path)
    generations = [g.to_dict() for g in store.list()]
    jobs = [j.to_dict() for j in outbox.list()]
    return {
        "indexes": generations,
        "jobs": jobs,
        "backends": [m.__dict__ for m in registry.manifests()],
        "embeddings": [m.to_dict() for m in embedding_registry.list()],
        "findings": [f.to_dict() for f in retrieval_diagnose(workspace_path)],
    }


def retrieval_diagnose(workspace_path: str | Path) -> list[DiagnosticFinding]:
    workspace = Path(workspace_path)
    store = JsonlIndexGenerationStore(workspace_path)
    generations = store.list()
    findings: list[DiagnosticFinding] = []
    by_key: dict[tuple[str, str, str], list] = {}
    for generation in generations:
        key = (generation.logical_index, generation.workspace_id, generation.project_id)
        by_key.setdefault(key, []).append(generation)
        if generation.state == IndexGenerationState.FAILED:
            findings.append(
                DiagnosticFinding(
                    code="GENERATION_BUILD_FAILED",
                    severity="error",
                    component="retrieval",
                    message="A retrieval index generation failed to build.",
                    remediation="Inspect the failure reason and run retrieval index rebuild.",
                    details={"generation_id": generation.generation_id},
                )
            )
        if not generation.metadata.get("backend_binding"):
            findings.append(
                DiagnosticFinding(
                    code="GENERATION_BACKEND_BINDING_MISSING",
                    severity="warning",
                    component="retrieval",
                    message="Generation metadata has no backend binding.",
                    remediation="Rebuild the index with the production index manager.",
                    details={"generation_id": generation.generation_id},
                )
            )
        if generation.state == IndexGenerationState.SHADOW and not generation.verified:
            findings.append(
                DiagnosticFinding(
                    code="GENERATION_NOT_VERIFIED",
                    severity="warning",
                    component="retrieval",
                    message="A shadow retrieval index generation has not been verified.",
                    remediation="Run retrieval index verify before activation.",
                    details={"generation_id": generation.generation_id},
                )
            )
    for (logical_index, workspace_id, project_id), items in by_key.items():
        active = [g for g in items if g.state == IndexGenerationState.ACTIVE]
        if not active:
            findings.append(
                DiagnosticFinding(
                    code="NO_ACTIVE_GENERATION",
                    severity="warning",
                    component="retrieval",
                    message="No active retrieval index generation exists.",
                    remediation="Run retrieval index rebuild.",
                    details={
                        "logical_index": logical_index,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                    },
                )
            )
        if len(active) > 1:
            findings.append(
                DiagnosticFinding(
                    code="MULTIPLE_ACTIVE_GENERATIONS",
                    severity="error",
                    component="retrieval",
                    message="More than one active generation exists for the same logical index.",
                    remediation="Retire older active generations.",
                    details={
                        "logical_index": logical_index,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "generation_ids": [g.generation_id for g in active],
                    },
                )
            )
    findings.extend(_local_data_plane_findings(workspace, generations))
    return findings


def _local_data_plane_findings(workspace: Path, generations: list) -> list[DiagnosticFinding]:
    if not generations:
        return []
    database = workspace / "retrieval" / "local_index.sqlite3"
    if not database.is_file():
        return [
            DiagnosticFinding(
                code="LOCAL_INDEX_DATABASE_MISSING",
                severity="error",
                component="retrieval",
                message="Retrieval control-plane metadata exists but the local SQLite index is missing.",
                remediation="Run retrieval index rebuild.",
                details={"database": str(database)},
            )
        ]
    required = {"retrieval_records", "generation_records", "backend_metadata"}
    conn = None
    try:
        conn = sqlite3.connect(database)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {str(row[0]) for row in rows}
    except Exception as exc:
        return [
            DiagnosticFinding(
                code="LOCAL_INDEX_SCHEMA_MISMATCH",
                severity="error",
                component="retrieval",
                message="Local retrieval SQLite index cannot be inspected.",
                remediation="Rebuild the local retrieval index.",
                details={"database": str(database), "error": str(exc)},
            )
        ]
    finally:
        if conn is not None:
            conn.close()
    missing = sorted(required - tables)
    if not missing:
        return []
    return [
        DiagnosticFinding(
            code="LOCAL_INDEX_SCHEMA_MISMATCH",
            severity="error",
            component="retrieval",
            message="Local retrieval SQLite index is missing required tables.",
            remediation="Rebuild the local retrieval index.",
            details={"database": str(database), "missing_tables": missing},
        )
    ]
