"""SQLite-backed local retrieval backend."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nous_runtime.retrieval.backends.local import _score_record, _snippet, _terms
from nous_runtime.retrieval.filters import record_matches_filters, record_matches_scope
from nous_runtime.retrieval.models import RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import (
    BackendHealth,
    BackendSearchRequest,
    BackendSearchResult,
    BackendWriteResult,
    IndexSpec,
    IndexVerification,
    RetrievalBackendManifest,
)


@dataclass
class PersistentLocalRetrievalBackend:
    workspace_path: str | Path
    database_path: str | Path | None = None
    write_generation_id: str = ""

    def __post_init__(self) -> None:
        self.workspace_path = Path(self.workspace_path)
        self.database_path = Path(self.database_path) if self.database_path else (
            self.workspace_path / "retrieval" / "local_index.sqlite3"
        )
        self._fts_available = False
        self._ensure_schema()

    @property
    def records(self) -> dict[str, RetrievalRecord]:
        return {record.record_id: record for record in self._load_records()}

    def manifest(self) -> RetrievalBackendManifest:
        return RetrievalBackendManifest(
            name="persistent_local",
            version="1.0",
            supports_dense=False,
            supports_sparse=False,
            supports_lexical=True,
            supports_filters=True,
            supports_upsert=True,
            supports_delete=True,
            multi_tenant=True,
            metadata={"storage": "sqlite", "path": str(self.database_path)},
        )

    def ensure_index(self, spec: IndexSpec) -> BackendWriteResult:
        self.write_generation_id = str(spec.metadata.get("generation_id") or self.write_generation_id)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO backend_metadata(key, value_json)
                VALUES(?, ?)
                """,
                (f"index:{spec.name}", json.dumps(spec.metadata, ensure_ascii=False, sort_keys=True)),
            )
        return BackendWriteResult(ok=True, count=1)

    def upsert(self, records: list[RetrievalRecord], generation_id: str | None = None) -> BackendWriteResult:
        gen = generation_id or self.write_generation_id
        if not gen:
            return BackendWriteResult(ok=False, errors=("generation_id is required for persistent local upsert",))
        with self._connection() as conn:
            self._delete_fts_records(conn, gen, [record.record_id for record in records])
            for record in records:
                data = record.to_dict()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO retrieval_records(
                        generation_id, record_id, workspace_id, project_id, record_type,
                        source_type, stable_key, active, content, content_hash,
                        metadata_json, record_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gen,
                        record.record_id,
                        record.workspace_id,
                        record.project_id,
                        record.record_type,
                        record.source_type,
                        record.stable_key or "",
                        1 if record.active else 0,
                        record.content,
                        record.content_hash,
                        json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                        json.dumps(data, ensure_ascii=False, sort_keys=True),
                        data["created_at"],
                        data["updated_at"],
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO generation_records(generation_id, record_id)
                    VALUES(?, ?)
                    """,
                    (gen, record.record_id),
                )
                self._upsert_fts(conn, gen, record)
        return BackendWriteResult(ok=True, count=len(records))

    def delete(self, record_ids: list[str], scope: RetrievalScope) -> BackendWriteResult:
        count = 0
        with self._connection() as conn:
            for record_id in record_ids:
                rows = conn.execute(
                    """
                    SELECT generation_id, record_json FROM retrieval_records
                    WHERE record_id=? AND workspace_id=? AND project_id IN (%s)
                    """ % _placeholders(len(scope.project_ids)),
                    (record_id, scope.workspace_id, *scope.project_ids),
                ).fetchall()
                for row in rows:
                    record = RetrievalRecord.from_dict(json.loads(row["record_json"]))
                    if not record_matches_scope(record, scope):
                        continue
                    if self._fts_available:
                        conn.execute(
                            "DELETE FROM retrieval_records_fts WHERE generation_id=? AND record_id=?",
                            (row["generation_id"], record_id),
                        )
                    conn.execute(
                        "DELETE FROM retrieval_records WHERE generation_id=? AND record_id=?",
                        (row["generation_id"], record_id),
                    )
                    conn.execute(
                        "DELETE FROM generation_records WHERE generation_id=? AND record_id=?",
                        (row["generation_id"], record_id),
                    )
                    count += 1
        return BackendWriteResult(ok=True, count=count)

    def search(self, request: BackendSearchRequest) -> list[BackendSearchResult]:
        query = request.query
        terms = _terms(query.text)
        records = self._search_records(request)
        superseded_source_ids = {r.supersedes for r in records if r.supersedes}
        scored: list[tuple[float, RetrievalRecord, dict[str, float]]] = []
        for record in records:
            if not record_matches_scope(record, query.scope):
                continue
            if not record_matches_filters(record, query.filters, superseded_source_ids):
                continue
            score, explanation = _score_record(record, query.text, terms)
            if score <= 0 and query.text:
                continue
            scored.append((score, record, explanation))
        scored.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].record_id))
        return [
            BackendSearchResult(
                record_id=record.record_id,
                score=min(1.0, score),
                raw_score=score,
                matched_text=_snippet(record, query.text),
                explanation=explanation,
                record=record,
            )
            for score, record, explanation in scored[: query.limit]
        ]

    def health(self) -> BackendHealth:
        exists = Path(self.database_path).is_file()
        try:
            self._ensure_schema()
            return BackendHealth(ok=True, details={"database": str(self.database_path), "exists": exists})
        except Exception as exc:
            return BackendHealth(ok=False, status="error", details={"database": str(self.database_path), "error": str(exc)})

    def verify(self, spec: IndexSpec) -> IndexVerification:
        generation_id = str(spec.metadata.get("generation_id") or "")
        workspace_id = str(spec.metadata.get("workspace_id") or "")
        project_id = str(spec.metadata.get("project_id") or "")
        indexed_records = self.count(
            generation_id,
            RetrievalScope(workspace_id=workspace_id, project_ids=(project_id,)),
        ) if generation_id and workspace_id and project_id else 0
        return IndexVerification(
            ok=bool(generation_id) and self.generation_exists(generation_id),
            indexed_records=indexed_records,
            details={"index_name": spec.name, "generation_id": generation_id, "backend": "persistent_local"},
        )

    def list_record_ids(self, generation_id: str, scope: RetrievalScope) -> list[str]:
        records = self._load_records(generation_id=generation_id, scope=scope)
        return sorted(record.record_id for record in records if record_matches_scope(record, scope))

    def count(self, generation_id: str, scope: RetrievalScope) -> int:
        return len(self.list_record_ids(generation_id, scope))

    def clear_generation(self, generation_id: str) -> BackendWriteResult:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_records WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
            count = int(row["count"] if row else 0)
            if self._fts_available:
                conn.execute("DELETE FROM retrieval_records_fts WHERE generation_id=?", (generation_id,))
            conn.execute("DELETE FROM retrieval_records WHERE generation_id=?", (generation_id,))
            conn.execute("DELETE FROM generation_records WHERE generation_id=?", (generation_id,))
        return BackendWriteResult(ok=True, count=count)

    def generation_exists(self, generation_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM generation_records WHERE generation_id=? LIMIT 1",
                (generation_id,),
            ).fetchone()
        return row is not None

    def _search_records(self, request: BackendSearchRequest) -> list[RetrievalRecord]:
        query = request.query
        terms = _terms(query.text)
        if not terms:
            return self._load_records(generation_id=request.generation_id, scope=query.scope)
        if not self._fts_available or any(ord(character) > 127 for character in query.text):
            return self._search_records_like(request, terms)
        expression = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        where = [
            "retrieval_records_fts MATCH ?",
            "records.workspace_id=?",
            f"records.project_id IN ({_placeholders(len(query.scope.project_ids))})",
        ]
        args: list[Any] = [expression, query.scope.workspace_id, *query.scope.project_ids]
        if request.generation_id:
            where.append("records.generation_id=?")
            args.append(request.generation_id)
        candidate_limit = min(max((query.limit * 3 + 1) // 2, 100), 2000)
        sql = """
            SELECT records.record_json
            FROM retrieval_records_fts
            JOIN retrieval_records AS records
              ON records.generation_id = retrieval_records_fts.generation_id
             AND records.record_id = retrieval_records_fts.record_id
            WHERE %s
            ORDER BY bm25(retrieval_records_fts), records.updated_at DESC, records.record_id
            LIMIT ?
        """ % " AND ".join(where)
        args.append(candidate_limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return self._search_records_like(request, terms)
        if not rows:
            return self._search_records_like(request, terms)
        return [RetrievalRecord.from_dict(json.loads(row["record_json"])) for row in rows]

    def _search_records_like(
        self,
        request: BackendSearchRequest,
        terms: list[str],
    ) -> list[RetrievalRecord]:
        scope = request.query.scope
        where = [
            "workspace_id=?",
            f"project_id IN ({_placeholders(len(scope.project_ids))})",
        ]
        args: list[Any] = [scope.workspace_id, *scope.project_ids]
        if request.generation_id:
            where.append("generation_id=?")
            args.append(request.generation_id)
        term_clauses: list[str] = []
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            term_clauses.append("LOWER(record_json) LIKE ? ESCAPE '\\'")
            args.append(f"%{escaped.lower()}%")
        where.append("(" + " OR ".join(term_clauses) + ")")
        sql = "SELECT record_json FROM retrieval_records WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, record_id"
        with self._connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [RetrievalRecord.from_dict(json.loads(row["record_json"])) for row in rows]

    def _delete_fts_records(
        self,
        conn: sqlite3.Connection,
        generation_id: str,
        record_ids: list[str],
    ) -> None:
        if not self._fts_available:
            return
        for offset in range(0, len(record_ids), 500):
            batch = record_ids[offset:offset + 500]
            if not batch:
                continue
            conn.execute(
                "DELETE FROM retrieval_records_fts WHERE generation_id=? AND record_id IN (%s)"
                % _placeholders(len(batch)),
                (generation_id, *batch),
            )

    def _upsert_fts(self, conn: sqlite3.Connection, generation_id: str, record: RetrievalRecord) -> None:
        if not self._fts_available:
            return
        conn.execute(
            """
            INSERT INTO retrieval_records_fts(
                generation_id, record_id, workspace_id, project_id,
                title, content, stable_key, source_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                record.record_id,
                record.workspace_id,
                record.project_id,
                record.title or "",
                record.content,
                record.stable_key or "",
                record.source_id,
            ),
        )

    def _backfill_fts(self, conn: sqlite3.Connection) -> None:
        if not self._fts_available:
            return
        indexed = conn.execute("SELECT COUNT(*) AS count FROM retrieval_records_fts").fetchone()
        if indexed and int(indexed["count"]) > 0:
            return
        rows = conn.execute("SELECT generation_id, record_json FROM retrieval_records").fetchall()
        for row in rows:
            record = RetrievalRecord.from_dict(json.loads(row["record_json"]))
            self._upsert_fts(conn, str(row["generation_id"]), record)
    def _load_records(
        self,
        *,
        generation_id: str = "",
        scope: RetrievalScope | None = None,
    ) -> list[RetrievalRecord]:
        sql = "SELECT record_json FROM retrieval_records"
        args: list[Any] = []
        where: list[str] = []
        if generation_id:
            where.append("generation_id=?")
            args.append(generation_id)
        if scope:
            where.append("workspace_id=?")
            args.append(scope.workspace_id)
            where.append(f"project_id IN ({_placeholders(len(scope.project_ids))})")
            args.extend(scope.project_ids)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, record_id"
        with self._connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [RetrievalRecord.from_dict(json.loads(row["record_json"])) for row in rows]

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_records (
                    generation_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    stable_key TEXT,
                    active INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (generation_id, record_id)
                );

                CREATE TABLE IF NOT EXISTS generation_records (
                    generation_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    PRIMARY KEY (generation_id, record_id)
                );

                CREATE TABLE IF NOT EXISTS backend_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_retrieval_scope
                    ON retrieval_records(workspace_id, project_id);
                CREATE INDEX IF NOT EXISTS idx_retrieval_generation
                    ON retrieval_records(generation_id);
                CREATE INDEX IF NOT EXISTS idx_retrieval_record_type
                    ON retrieval_records(record_type);
                CREATE INDEX IF NOT EXISTS idx_retrieval_stable_key
                    ON retrieval_records(stable_key);
                CREATE INDEX IF NOT EXISTS idx_retrieval_active
                    ON retrieval_records(active);
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_records_fts USING fts5(
                        generation_id UNINDEXED,
                        record_id UNINDEXED,
                        workspace_id UNINDEXED,
                        project_id UNINDEXED,
                        title,
                        content,
                        stable_key,
                        source_id
                    )
                    """
                )
                self._fts_available = True
                self._backfill_fts(conn)
            except sqlite3.OperationalError:
                self._fts_available = False


def _placeholders(count: int) -> str:
    if count < 1:
        raise ValueError("at least one value is required")
    return ", ".join("?" for _ in range(count))
