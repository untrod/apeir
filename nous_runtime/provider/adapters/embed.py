# -*- coding: utf-8 -*-
"""Embedding Provider -model.embed."""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.embed")


class FastEmbedProvider(Provider):
    """Provider for text embedding (fastembed / BGE models)."""

    name = "fastembed"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["model.embed"]

    def invoke(self, capability_id: str, **params) -> dict:
        text = params.get("text", "")
        try:
            from remote_terminal.embedding import embed_text
            vector = embed_text(text)
            return {"ok": True, "vector_dim": len(vector) if vector else 0}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            from remote_terminal.embedding import embed_text
            v = embed_text("health check")
            return {"status": "ok", "dim": len(v) if v else 0}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}
