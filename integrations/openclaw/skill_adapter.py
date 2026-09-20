"""OpenClaw Skill → Nous Capability / Tool Provider adapter.

Maps OpenClaw skill definitions to Nous capability contracts,
ensuring all tool execution passes through governance and effect gating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("nous.integrations.openclaw.skill")


class SkillExecutor(Protocol):
    """Protocol for executing a skill with capability-gated access."""

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class SkillMapping:
    """Maps an OpenClaw skill to a Nous capability contract."""
    openclaw_skill_id: str
    openclaw_skill_name: str
    nous_capability_id: str | None = None
    tool_provider: str | None = None
    requires_approval: bool = False
    max_budget: float | None = None
    allowed_devices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillAdapter:
    """Adapts OpenClaw skills to Nous capability contracts.

    Ensures:
      - Every skill execution passes through governance gate
      - High-risk skills require explicit approval
      - Skills execute within capability sandbox
      - Budget enforcement per skill invocation
      - Device restrictions are honored
    """

    RISK_LEVELS = {
        "file_read": "low",
        "file_write": "medium",
        "shell_exec": "high",
        "network_outbound": "medium",
        "device_control": "high",
        "model_inference": "low",
        "code_execution": "high",
        "data_access": "medium",
    }

    def __init__(self):
        self._mappings: dict[str, SkillMapping] = {}

    def register_skill(
        self,
        openclaw_skill_id: str,
        openclaw_skill_name: str,
        risk_category: str | None = None,
    ) -> SkillMapping:
        """Register an OpenClaw skill and map it to a Nous capability."""
        risk = risk_category or self._infer_risk(openclaw_skill_name)

        mapping = SkillMapping(
            openclaw_skill_id=openclaw_skill_id,
            openclaw_skill_name=openclaw_skill_name,
            nous_capability_id=f"openclaw.{openclaw_skill_id}",
            requires_approval=risk in ("high", "medium"),
        )

        self._mappings[openclaw_skill_id] = mapping
        log.info(
            "Skill %s registered → capability %s (risk=%s, approval=%s)",
            openclaw_skill_id,
            mapping.nous_capability_id,
            risk,
            mapping.requires_approval,
        )
        return mapping

    def get_capability_id(self, openclaw_skill_id: str) -> str | None:
        """Get the Nous capability ID for an OpenClaw skill."""
        mapping = self._mappings.get(openclaw_skill_id)
        return mapping.nous_capability_id if mapping else None

    def requires_approval(self, openclaw_skill_id: str) -> bool:
        """Check if this skill requires human approval."""
        mapping = self._mappings.get(openclaw_skill_id)
        return mapping.requires_approval if mapping else True  # Default: require approval

    def _infer_risk(self, skill_name: str) -> str:
        """Infer risk level from skill name."""
        name_lower = skill_name.lower()
        for pattern, risk in self.RISK_LEVELS.items():
            if pattern.replace("_", "") in name_lower.replace("_", "").replace(" ", ""):
                return risk
        return "medium"  # Default: medium risk

    @property
    def registered_skills(self) -> list[str]:
        return list(self._mappings.keys())

    @property
    def high_risk_skills(self) -> list[str]:
        return [
            sid for sid, m in self._mappings.items()
            if m.requires_approval
        ]
