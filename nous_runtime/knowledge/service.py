"""Knowledge Library lifecycle built on the Retrieval Fabric."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from nous_runtime.knowledge.models import KnowledgeDocument, KnowledgeLibrary, KnowledgeResult
from nous_runtime.knowledge.store import KnowledgeStore
from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import AccessScope, RetrievalFilters, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import IndexSpec
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry


class KnowledgeLibraryService:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()
        self.store = KnowledgeStore(self.root)
        self.backend = PersistentLocalRetrievalBackend(self.root)
        registry = RetrievalBackendRegistry()
        registry.register(self.backend, name="local")
        self.gateway = RetrievalGateway(backend_registry=registry, default_backend="local", logical_index="knowledge")

    def create(self, workspace_id: str, owner_id: str, name: str) -> KnowledgeLibrary:
        return self.store.create_library(KnowledgeLibrary(workspace_id, owner_id, name))

    def import_file(self, library_id: str, path: str | Path, *, workspace_id: str, owner_id: str, logical_source: str = "") -> dict[str, Any]:
        library = self._require_library(library_id, workspace_id, owner_id)
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        content = self._read_text(source)
        logical = logical_source or source.name
        checksum = hashlib.sha256(content.encode()).hexdigest()
        current = self.store.get_document(library_id, logical)
        if current is not None and not current.deleted and current.checksum == checksum:
            return {"status": "unchanged", "document_id": current.document_id, "checksum": checksum}
        duplicate = self.store.active_by_checksum(library_id, checksum)
        document = KnowledgeDocument(library_id, logical, checksum, content, modified_ns=source.stat().st_mtime_ns, duplicate_of=duplicate.document_id if duplicate and (current is None or duplicate.document_id != current.document_id) else "")
        if current is not None and not current.deleted:
            self._delete_records(library, current)
        self.store.put_document(document)
        generation = library.active_generation or self._new_generation(library)
        if not document.duplicate_of:
            self.backend.upsert(self._records(library, document, generation), generation_id=generation)
        return {"status": "duplicate" if document.duplicate_of else ("modified" if current else "imported"), "document_id": document.document_id, "checksum": checksum, "duplicate_of": document.duplicate_of, "generation": generation}

    def delete_document(self, library_id: str, logical_source: str, *, workspace_id: str, owner_id: str) -> bool:
        library = self._require_library(library_id, workspace_id, owner_id)
        document = self.store.get_document(library_id, logical_source)
        if document is None or document.deleted:
            return False
        self._delete_records(library, document)
        changed = self.store.mark_deleted(library_id, logical_source)
        if changed:
            self.rebuild(library_id, workspace_id=workspace_id, owner_id=owner_id)
        return changed

    def rebuild(self, library_id: str, *, workspace_id: str, owner_id: str) -> str:
        library = self._require_library(library_id, workspace_id, owner_id)
        generation = self._new_generation(library, activate=False)
        by_checksum: dict[str, KnowledgeDocument] = {}
        for document in self.store.documents(library_id):
            by_checksum.setdefault(document.checksum, document)
        records: list[RetrievalRecord] = []
        for document in by_checksum.values():
            records.extend(self._records(library, document, generation))
        if records:
            result = self.backend.upsert(records, generation_id=generation)
            if not result.ok:
                self.backend.clear_generation(generation)
                raise RuntimeError("knowledge index rebuild failed: " + "; ".join(result.errors))
        scope = RetrievalScope(library.workspace_id, (self._project_id(library),), principal_id=library.owner_id)
        if self.backend.count(generation, scope) != len(records):
            self.backend.clear_generation(generation)
            raise RuntimeError("knowledge index verification failed")
        self.store.set_generation(library_id, generation)
        return generation

    def search(self, library_id: str, text: str, *, workspace_id: str, owner_id: str, limit: int = 10) -> list[KnowledgeResult]:
        library = self._require_library(library_id, workspace_id, owner_id)
        if not library.active_generation:
            return []
        query = RetrievalQuery(text, RetrievalScope(workspace_id, (self._project_id(library),), principal_id=owner_id), filters=RetrievalFilters(record_types=("document_chunk",), metadata_equals={"library_id": library_id}), limit=limit, mode="lexical", include_trace=True)
        results = self.gateway.search(query, generation_id=library.active_generation)
        return [KnowledgeResult(library_id, str(item.record.metadata.get("document_id") or ""), str(item.record.metadata.get("logical_source") or ""), str(item.record.metadata.get("chunk_id") or item.record.record_id), item.score, item.matched_text or item.record.content[:240], library.active_generation) for item in results]

    def export(self, library_id: str, *, workspace_id: str, owner_id: str) -> dict[str, Any]:
        library = self._require_library(library_id, workspace_id, owner_id)
        return {"schema_version": "1.0", "library": {"name": library.name}, "documents": [dict(document.__dict__) for document in self.store.documents(library_id)]}

    def import_export(self, data: dict[str, Any], *, workspace_id: str, owner_id: str) -> KnowledgeLibrary:
        library = self.create(workspace_id, owner_id, str((data.get("library") or {}).get("name") or "Imported Library"))
        for item in data.get("documents") or []:
            self.store.put_document(KnowledgeDocument(library.library_id, str(item["logical_source"]), str(item["checksum"]), str(item["content"]), modified_ns=int(item.get("modified_ns") or 0), duplicate_of=str(item.get("duplicate_of") or "")))
        self.rebuild(library.library_id, workspace_id=workspace_id, owner_id=owner_id)
        return self.store.get_library(library.library_id, workspace_id=workspace_id, owner_id=owner_id) or library

    def _require_library(self, library_id: str, workspace_id: str, owner_id: str) -> KnowledgeLibrary:
        library = self.store.get_library(library_id, workspace_id=workspace_id, owner_id=owner_id)
        if library is None:
            raise PermissionError("knowledge library is unavailable in this workspace and owner scope")
        return library

    def _new_generation(self, library: KnowledgeLibrary, *, activate: bool = True) -> str:
        generation = f"kg_{uuid.uuid4().hex}"
        self.backend.ensure_index(IndexSpec("knowledge", ("document_chunk",), metadata={"generation_id": generation, "workspace_id": library.workspace_id, "project_id": self._project_id(library)}))
        if activate:
            self.store.set_generation(library.library_id, generation)
        return generation

    def _records(self, library: KnowledgeLibrary, document: KnowledgeDocument, generation: str) -> list[RetrievalRecord]:
        chunks = self._chunks(document.content)
        records: list[RetrievalRecord] = []
        project_id = self._project_id(library)
        for index, chunk in enumerate(chunks):
            chunk_id = f"{document.document_id}:{index}"
            record_id = "kr_" + hashlib.sha256(f"{library.library_id}:{chunk_id}:{hash_content(chunk)}".encode()).hexdigest()[:32]
            records.append(RetrievalRecord(record_id, "document_chunk", library.workspace_id, project_id, document.document_id, "knowledge_library", chunk, hash_content(chunk), AccessScope(library.workspace_id, (project_id,), (library.owner_id,), "private"), title=document.logical_source, stable_key=chunk_id, metadata={"library_id": library.library_id, "document_id": document.document_id, "logical_source": document.logical_source, "chunk_id": chunk_id, "index_generation": generation}, index_status="indexed"))
        return records

    def _delete_records(self, library: KnowledgeLibrary, document: KnowledgeDocument) -> None:
        scope = RetrievalScope(library.workspace_id, (self._project_id(library),), principal_id=library.owner_id)
        ids = [record.record_id for record in self._records(library, document, library.active_generation)]
        if ids:
            self.backend.delete(ids, scope)

    @staticmethod
    def _chunks(content: str, size: int = 1000, overlap: int = 100) -> list[str]:
        if not content:
            return [""]
        step = size - overlap
        return [content[index:index + size] for index in range(0, len(content), step)]

    @staticmethod
    def _project_id(library: KnowledgeLibrary) -> str:
        return f"library.{library.library_id}"

    @staticmethod
    def _read_text(path: Path) -> str:
        if path.suffix.lower() not in {".txt", ".md", ".json", ".py", ".js", ".ts", ".java", ".rs", ".go", ".toml", ".yaml", ".yml"}:
            raise ValueError("unsupported knowledge document format")
        return path.read_text(encoding="utf-8")