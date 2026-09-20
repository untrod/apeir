"""Workspace-scoped governed Document IR lifecycle and export service."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from nous_runtime.artifact import ArtifactManager, ArtifactRegistry, ArtifactType
from nous_runtime.documents.models import DocumentIR, DocumentValidationError
from nous_runtime.documents.renderers import render_docx, render_pdf
from nous_runtime.documents.verification import verify_docx, verify_pdf
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.locking import file_lock

_FORMATS = {"docx", "pdf"}


class DocumentNotFoundError(DocumentValidationError):
    """Requested Document IR is not present in this workspace."""


class DocumentRuntime:
    """Canonical workspace authority for Document IR and rendered outputs."""

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise DocumentValidationError("the active workspace does not exist")
        self.storage = self.root / ".nous" / "documents"
        self.outputs = self.root / "artifacts" / "documents"
        self.storage.mkdir(parents=True, exist_ok=True)
        self.events = EventStream(str(self.root))
        self.artifacts = ArtifactManager(ArtifactRegistry(self.root / ".nous" / "artifacts.jsonl"))

    def status(self) -> dict[str, Any]:
        dependencies = {}
        for module in ("docx", "reportlab", "pypdf"):
            try:
                __import__(module)
                dependencies[module] = True
            except ImportError:
                dependencies[module] = False
        records = self.list_documents()
        return {
            "schema_version": "nous.document-runtime/v1",
            "workspace": str(self.root),
            "documents": len(records),
            "dependencies": dependencies,
            "formats": {"docx": dependencies["docx"], "pdf": dependencies["reportlab"] and dependencies["pypdf"]},
            "limits": {"blocks": 500, "content_characters": 500000, "output_bytes": 52428800},
            "event_authority": "EventStream",
            "artifact_authority": "ArtifactRegistry",
        }

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        document = DocumentIR.from_mapping(value, new_identity=True)
        run_id = f"document-create-{uuid4().hex}"
        task_id = f"document.create:{document.document_id}"
        self._start(run_id, task_id, "document.create", {"document_id": document.document_id, "ir_sha256": document.digest()})
        try:
            path = self._document_path(document.document_id)
            self._write_ir(path, document)
            artifact = self.artifacts.create(
                ArtifactType.DOCUMENT,
                f"Document IR: {document.title}",
                location=path.relative_to(self.root).as_posix(),
                creator="document.runtime",
                metadata={"document_id": document.document_id, "format": "document-ir", "sha256": document.digest(), "schema_version": document.schema_version},
            )
            self._emit(run_id, task_id, "document.created", {"document_id": document.document_id, "ir_sha256": document.digest(), "path": path.relative_to(self.root).as_posix()})
            self._artifact_event(run_id, task_id, artifact)
            self.events.emit_state_change(run_id, RunState.COMPLETED, task_id=task_id, document_id=document.document_id, artifact_id=artifact.id)
            return {**document.to_dict(), "artifact_id": artifact.id, "run_id": run_id}
        except Exception as exc:
            self.events.emit_state_change(run_id, RunState.FAILED, task_id=task_id, error=str(exc), document_id=document.document_id)
            raise

    def get(self, document_id: str) -> dict[str, Any]:
        return self._load(document_id).to_dict()

    def list_documents(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.storage.glob("doc_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                document = self._read_ir(path)
                records.append({
                    "document_id": document.document_id,
                    "title": document.title,
                    "subtitle": document.subtitle,
                    "preset": document.preset,
                    "created_at": document.created_at,
                    "block_count": len(document.blocks),
                    "sha256": document.digest(),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                records.append({"document_id": path.stem, "status": "invalid", "error": "IR integrity validation failed"})
        return records

    def render(self, document_id: str, formats: Sequence[str] | None = None) -> dict[str, Any]:
        document = self._load(document_id)
        requested = tuple(dict.fromkeys(str(item).strip().lower() for item in (formats or ("docx", "pdf"))))
        if not requested or any(item not in _FORMATS for item in requested):
            raise DocumentValidationError("formats must contain docx and/or pdf")
        run_id = f"document-render-{uuid4().hex}"
        task_id = f"document.render:{document.document_id}"
        self._start(run_id, task_id, "document.render", {"document_id": document.document_id, "formats": list(requested), "ir_sha256": document.digest()})
        outputs: list[dict[str, Any]] = []
        try:
            stem = self._safe_stem(document.title, document.document_id)
            for kind in requested:
                target = (self.outputs / f"{stem}.{kind}").resolve()
                staging = (self.outputs / f".{stem}-{run_id}.{kind}").resolve()
                if self.outputs.resolve() not in target.parents or self.outputs.resolve() not in staging.parents:
                    raise DocumentValidationError("render target escaped the document artifact directory")
                try:
                    if kind == "docx":
                        render_docx(document, staging)
                        verification = verify_docx(staging, document)
                    else:
                        render_pdf(document, staging)
                        verification = verify_pdf(staging, document)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging, target)
                    verification["path"] = str(target)
                finally:
                    staging.unlink(missing_ok=True)
                artifact = self.artifacts.create(
                    ArtifactType.DOCUMENT,
                    f"{kind.upper()} document: {document.title}",
                    location=target.relative_to(self.root).as_posix(),
                    creator="document.runtime",
                    metadata={
                        "document_id": document.document_id, "format": kind,
                        "sha256": verification["sha256"], "size_bytes": verification["size_bytes"],
                        "verified": True, "ir_sha256": document.digest(),
                        "page_count": verification.get("page_count"),
                    },
                )
                output = {**verification, "artifact_id": artifact.id, "location": artifact.location}
                outputs.append(output)
                self._emit(run_id, task_id, "document.rendered", {"document_id": document.document_id, "format": kind, "artifact_id": artifact.id, "location": artifact.location, "sha256": verification["sha256"]})
                self._emit(run_id, task_id, "document.verified", {"document_id": document.document_id, "format": kind, "artifact_id": artifact.id, "checks": verification["checks"], "ok": True})
                self._artifact_event(run_id, task_id, artifact)
            self.events.emit_state_change(run_id, RunState.COMPLETED, task_id=task_id, document_id=document.document_id, artifact_ids=[item["artifact_id"] for item in outputs])
            return {"document_id": document.document_id, "ir_sha256": document.digest(), "run_id": run_id, "outputs": outputs, "verified": True}
        except Exception as exc:
            self._emit(run_id, task_id, "document.failed", {"document_id": document.document_id, "error": str(exc)})
            self.events.emit_state_change(run_id, RunState.FAILED, task_id=task_id, error=str(exc), document_id=document.document_id)
            raise

    def _document_path(self, document_id: str) -> Path:
        if not re.fullmatch(r"doc_[a-f0-9]{32}", str(document_id)):
            raise DocumentValidationError("document_id is invalid")
        target = (self.storage / f"{document_id}.json").resolve()
        if target.parent != self.storage.resolve():
            raise DocumentValidationError("document path escaped storage")
        return target

    def _load(self, document_id: str) -> DocumentIR:
        path = self._document_path(document_id)
        if not path.is_file():
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return self._read_ir(path)

    @staticmethod
    def _safe_stem(title: str, document_id: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip(".-")[:80]
        return f"{stem or 'document'}-{document_id[-12:]}"

    @staticmethod
    def _read_ir(path: Path) -> DocumentIR:
        with file_lock(str(path) + ".lock"):
            value = json.loads(path.read_text(encoding="utf-8"))
        expected = str(value.pop("sha256", ""))
        document = DocumentIR.from_mapping(value)
        if not expected or expected != document.digest():
            raise DocumentValidationError("Document IR integrity digest mismatch")
        return document

    @staticmethod
    def _write_ir(path: Path, document: DocumentIR) -> None:
        payload = json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with file_lock(str(path) + ".lock"):
            descriptor, temporary = tempfile.mkstemp(prefix=".nous-ir-", suffix=".json", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _start(self, run_id: str, task_id: str, operation: str, metadata: dict[str, Any]) -> None:
        self.events.create_run(run_id, task_id=task_id, total_steps=1, metadata={"authority": "EventStream", "operation": operation, **metadata})
        self.events.emit_state_change(run_id, RunState.CREATED, task_id=task_id, operation=operation, **metadata)
        self.events.emit(RunEvent(run_id=run_id, task_id=task_id, event_type="command.proposed", actor="document.runtime", payload={"operation": operation, **metadata}))
        self.events.emit_state_change(run_id, RunState.RUNNING, task_id=task_id, operation=operation)

    def _emit(self, run_id: str, task_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.events.emit(RunEvent(run_id=run_id, task_id=task_id, event_type=event_type, actor="document.runtime", payload=payload))

    def _artifact_event(self, run_id: str, task_id: str, artifact) -> None:
        self._emit(run_id, task_id, "artifact.created", {"artifact_id": artifact.id, "artifact_type": artifact.type, "location": artifact.location, "document_id": artifact.metadata.get("document_id", "")})


__all__ = ["DocumentNotFoundError", "DocumentRuntime"]