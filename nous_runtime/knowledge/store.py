"""Knowledge Library metadata store."""

from __future__ import annotations

from contextlib import contextmanager

import sqlite3
from pathlib import Path

from nous_runtime.knowledge.models import KnowledgeDocument, KnowledgeLibrary


class KnowledgeStore:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()
        self.path = self.root / ".nous" / "knowledge.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS libraries (
                    library_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL, name TEXT NOT NULL, active_generation TEXT NOT NULL DEFAULT '',
                    UNIQUE(workspace_id, owner_id, name)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, library_id TEXT NOT NULL,
                    logical_source TEXT NOT NULL, checksum TEXT NOT NULL, content TEXT NOT NULL,
                    modified_ns INTEGER NOT NULL DEFAULT 0, duplicate_of TEXT NOT NULL DEFAULT '',
                    deleted INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(library_id) REFERENCES libraries(library_id) ON DELETE CASCADE,
                    UNIQUE(library_id, logical_source)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_checksum ON documents(library_id, checksum, deleted);
                """
            )

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def create_library(self, library: KnowledgeLibrary) -> KnowledgeLibrary:
        if not library.workspace_id or not library.owner_id or not library.name:
            raise ValueError("workspace_id, owner_id, and name are required")
        with self._db() as connection:
            connection.execute("INSERT INTO libraries VALUES (?, ?, ?, ?, ?)", (library.library_id, library.workspace_id, library.owner_id, library.name, library.active_generation))
        return library

    def get_library(self, library_id: str, *, workspace_id: str = "", owner_id: str = "") -> KnowledgeLibrary | None:
        clauses = ["library_id = ?"]
        values = [library_id]
        if workspace_id:
            clauses.append("workspace_id = ?")
            values.append(workspace_id)
        if owner_id:
            clauses.append("owner_id = ?")
            values.append(owner_id)
        with self._db() as connection:
            row = connection.execute("SELECT * FROM libraries WHERE " + " AND ".join(clauses), values).fetchone()
        return KnowledgeLibrary(row["workspace_id"], row["owner_id"], row["name"], row["library_id"], row["active_generation"]) if row else None

    def list_libraries(self, *, workspace_id: str, owner_id: str) -> list[KnowledgeLibrary]:
        with self._db() as connection:
            rows = connection.execute("SELECT * FROM libraries WHERE workspace_id = ? AND owner_id = ? ORDER BY name", (workspace_id, owner_id)).fetchall()
        return [KnowledgeLibrary(row["workspace_id"], row["owner_id"], row["name"], row["library_id"], row["active_generation"]) for row in rows]

    def put_document(self, document: KnowledgeDocument) -> None:
        with self._db() as connection:
            connection.execute("""INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(library_id, logical_source) DO UPDATE SET document_id=excluded.document_id,
                checksum=excluded.checksum, content=excluded.content, modified_ns=excluded.modified_ns,
                duplicate_of=excluded.duplicate_of, deleted=0""", (document.document_id, document.library_id, document.logical_source, document.checksum, document.content, document.modified_ns, document.duplicate_of, int(document.deleted)))

    def get_document(self, library_id: str, logical_source: str) -> KnowledgeDocument | None:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM documents WHERE library_id = ? AND logical_source = ?", (library_id, logical_source)).fetchone()
        return self._document(row) if row else None

    def documents(self, library_id: str, *, include_deleted: bool = False) -> list[KnowledgeDocument]:
        query = "SELECT * FROM documents WHERE library_id = ?" + ("" if include_deleted else " AND deleted = 0") + " ORDER BY logical_source"
        with self._db() as connection:
            rows = connection.execute(query, (library_id,)).fetchall()
        return [self._document(row) for row in rows]

    def active_by_checksum(self, library_id: str, checksum: str) -> KnowledgeDocument | None:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM documents WHERE library_id = ? AND checksum = ? AND deleted = 0 AND duplicate_of = '' ORDER BY document_id LIMIT 1", (library_id, checksum)).fetchone()
        return self._document(row) if row else None

    def mark_deleted(self, library_id: str, logical_source: str) -> bool:
        with self._db() as connection:
            cursor = connection.execute("UPDATE documents SET deleted = 1 WHERE library_id = ? AND logical_source = ? AND deleted = 0", (library_id, logical_source))
        return cursor.rowcount == 1

    def set_generation(self, library_id: str, generation: str) -> None:
        with self._db() as connection:
            connection.execute("UPDATE libraries SET active_generation = ? WHERE library_id = ?", (generation, library_id))

    def delete_library(self, library_id: str) -> bool:
        with self._db() as connection:
            cursor = connection.execute("DELETE FROM libraries WHERE library_id = ?", (library_id,))
        return cursor.rowcount == 1

    @staticmethod
    def _document(row: sqlite3.Row) -> KnowledgeDocument:
        return KnowledgeDocument(row["library_id"], row["logical_source"], row["checksum"], row["content"], row["document_id"], int(row["modified_ns"]), row["duplicate_of"], bool(row["deleted"]))