# -*- coding: utf-8 -*-
"""Agent health helpers."""

from __future__ import annotations

from nous_runtime.agent.models import AgentHealth, AgentProfile, utc_now


def mark_healthy(profile: AgentProfile) -> AgentProfile:
    return AgentProfile(
        manifest=profile.manifest,
        state=profile.state,
        health=AgentHealth(status="ok", last_seen_at=utc_now(), failure_count=profile.health.failure_count),
        registered_at=profile.registered_at,
        updated_at=utc_now(),
    )


def mark_failed(profile: AgentProfile, error: str) -> AgentProfile:
    return AgentProfile(
        manifest=profile.manifest,
        state=profile.state,
        health=AgentHealth(
            status="failed",
            last_seen_at=utc_now(),
            failure_count=profile.health.failure_count + 1,
            last_error=error,
        ),
        registered_at=profile.registered_at,
        updated_at=utc_now(),
    )
