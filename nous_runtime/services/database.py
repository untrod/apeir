"""Database maintenance service used by public CLI commands."""

from __future__ import annotations


def run_migrations() -> int:
    """Run runtime database migrations."""
    from nous_runtime.compat.db import run_migrations as _run_migrations

    return _run_migrations()

