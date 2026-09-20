# -*- coding: utf-8 -*-
"""
nous_core ID generator.

All P0 entities use a uniform ID scheme: {prefix}_{timestamp}_{random}

Examples:
  evt_20260706_14a3f2b1
  job_20260706_9c2d8e4f
  dev_pc_main
  ntf_20260706_7b1a3c5d

Rules:
  - prefix is always lowercase, 3-4 chars
  - timestamp is compact: YYYYMMDD or YYYYMMDDHHMMSS
  - random is 8 hex chars (4 bytes)
  - fixed IDs (like device IDs) skip the random suffix
"""

from __future__ import annotations

import secrets as _secrets
import time as _time


def make_id(prefix: str, with_random: bool = True) -> str:
    """
    Generate a unique ID.

    Args:
      prefix: 3-4 char lowercase prefix (e.g. "evt", "job", "ntf")
      with_random: if True, append _XXXXXXXX random hex. Set False for
                   human-assigned stable IDs (e.g. device IDs).

    Returns:
      e.g. "evt_20260706_a3f2b1c0" or "dev_pc_main"
    """
    ts = _time.strftime("%Y%m%d")
    if with_random:
        rand = _secrets.token_hex(4)  # 8 hex chars
        return f"{prefix}_{ts}_{rand}"
    return prefix  # caller should append their own stable suffix


def make_evt_id() -> str:
    """Generate an event ID: evt_YYYYMMDD_XXXXXXXX"""
    return make_id("evt")


def make_job_id() -> str:
    """Generate a job ID: job_YYYYMMDD_XXXXXXXX"""
    return make_id("job")


def make_ntf_id() -> str:
    """Generate a notification ID: ntf_YYYYMMDD_XXXXXXXX"""
    return make_id("ntf")


def make_aud_id() -> str:
    """Generate an audit log ID: aud_YYYYMMDD_XXXXXXXX"""
    return make_id("aud")


# Correlation IDs are shared across a chain of events/jobs/notifications
def make_corr_id() -> str:
    """Generate a correlation ID: corr_YYYYMMDD_XXXXXXXX"""
    return make_id("corr")
