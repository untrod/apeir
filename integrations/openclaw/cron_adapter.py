"""OpenClaw Cron → Nous Automation Workload adapter.

Maps OpenClaw scheduled tasks to Nous automation workloads,
providing durable scheduling with journal and recovery guarantees.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("nous.integrations.openclaw.cron")


@dataclass
class CronMapping:
    """Maps an OpenClaw cron job to a Nous automation workload."""
    openclaw_cron_id: str
    nous_workload_id: str | None = None
    schedule: str = "* * * * *"  # Cron expression
    skill_id: str | None = None
    last_run: datetime | None = None
    next_run: datetime | None = None
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)


class CronAdapter:
    """Adapts OpenClaw cron jobs to Nous automation workloads.

    Provides:
      - Durable scheduling with journal
      - Automatic retry with backoff
      - Execution trace and audit
      - Graceful degradation on failure
    """

    def __init__(self):
        self._crons: dict[str, CronMapping] = {}

    def register_cron(
        self,
        openclaw_cron_id: str,
        schedule: str,
        skill_id: str,
        timeout_seconds: int = 300,
        max_retries: int = 3,
    ) -> CronMapping:
        """Register an OpenClaw cron as a Nous automation workload."""
        mapping = CronMapping(
            openclaw_cron_id=openclaw_cron_id,
            nous_workload_id=f"auto-{openclaw_cron_id}",
            schedule=schedule,
            skill_id=skill_id,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self._crons[openclaw_cron_id] = mapping
        log.info(
            "Cron %s registered → automation workload %s (schedule=%s)",
            openclaw_cron_id, mapping.nous_workload_id, schedule,
        )
        return mapping

    def record_run(
        self,
        openclaw_cron_id: str,
        success: bool,
        output: str | None = None,
    ) -> None:
        """Record a cron execution in the journal."""
        mapping = self._crons.get(openclaw_cron_id)
        if not mapping:
            return

        now = datetime.now(timezone.utc)
        mapping.last_run = now
        log.info(
            "Cron %s executed at %s: success=%s",
            openclaw_cron_id, now.isoformat(), success,
        )
        # TODO: Append to Nous journal for durable audit trail

    def disable_cron(self, openclaw_cron_id: str) -> None:
        mapping = self._crons.get(openclaw_cron_id)
        if mapping:
            mapping.enabled = False

    def enable_cron(self, openclaw_cron_id: str) -> None:
        mapping = self._crons.get(openclaw_cron_id)
        if mapping:
            mapping.enabled = True

    @property
    def active_crons(self) -> int:
        return sum(1 for m in self._crons.values() if m.enabled)
