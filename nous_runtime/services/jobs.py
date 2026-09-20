"""Job query service used by public runtime surfaces."""

from __future__ import annotations

from typing import Any


def list_jobs(
    status: str = "",
    job_type: str = "",
    session_id: str = "",
    device_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List runtime jobs through the service boundary."""
    try:
        from nous_runtime.compat.jobs import list_jobs as _list_jobs

        return _list_jobs(
            status=status,
            job_type=job_type,
            session_id=session_id,
            device_id=device_id,
            limit=limit,
            offset=offset,
        )
    except Exception:
        return []


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return one runtime job by id."""
    try:
        from nous_runtime.compat.jobs import get_job as _get_job

        return _get_job(job_id)
    except Exception:
        return None

