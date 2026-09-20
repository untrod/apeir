"""Stable hashing for derived retrieval content."""

from __future__ import annotations

import hashlib


def hash_content(content: str) -> str:
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()
