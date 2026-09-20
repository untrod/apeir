# -*- coding: utf-8 -*-
"""ChromaDB Provider -rag.search, rag.index."""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.chromadb")


class ChromaDBProvider(Provider):
    """Provider for vector search and indexing via ChromaDB."""

    name = "chromadb"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["rag.search", "rag.index"]

    def invoke(self, capability_id: str, **params) -> dict:
        action = "search" if capability_id.endswith("search") else "index"
        try:
            from remote_terminal.vector_store import (
                search_knowledge,
                search_documents,
                add_document_chunks,
            )
            if action == "search":
                query = params.get("query", "")
                top_k = params.get("top_k", 5)
                kp = search_knowledge(query, top_k=top_k)
                docs = search_documents(query, top_k=top_k)
                return {
                    "ok": True,
                    "knowledge_hits": len(kp),
                    "document_hits": len(docs),
                    "results": kp + docs,
                }
            elif action == "index":
                add_document_chunks(
                    params.get("doc_id", 0),
                    params.get("text", ""),
                    subject=params.get("subject", ""),
                )
                return {"ok": True, "indexed": True}
            return {"ok": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            from remote_terminal.vector_store import count
            n = count("knowledge_points") if hasattr(__import__("remote_terminal.vector_store", fromlist=["count"]), "count") else "? "
            return {"status": "ok", "chunks": n}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}
