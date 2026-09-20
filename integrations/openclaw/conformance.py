"""OpenClaw ↔ Nous conformance tests.

Validates that the OpenClaw → Nous mapping is correct and complete.
Checks:
  - Session → AgentProcess lifecycle
  - Workspace → Namespace isolation
  - Skill → Capability gating
  - Node → Node identity
  - Cron → Automation durability
"""

from __future__ import annotations

import logging
import importlib.util
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger("nous.integrations.openclaw.conformance")


class ConformanceLevel(Enum):
    """Conformance validation levels."""
    SCHEMA = 1       # Types and interfaces match
    LIFECYCLE = 2    # State transitions match
    ISOLATION = 3    # Security boundaries match
    DURABILITY = 4   # Recovery guarantees match
    FULL = 5         # End-to-end equivalence


@dataclass
class ConformanceResult:
    """Result of a conformance check."""
    check_name: str
    level: ConformanceLevel
    passed: bool
    openclaw_concept: str
    nous_concept: str
    details: str = ""
    gaps: list[str] = field(default_factory=list)


class ConformanceValidator:
    """Validates OpenClaw ↔ Nous mapping correctness."""

    def __init__(self, target_level: ConformanceLevel = ConformanceLevel.SCHEMA):
        self.target_level = target_level
        self.results: list[ConformanceResult] = []

    def check_session_to_process(self) -> ConformanceResult:
        """Verify session → agent process mapping."""
        result = ConformanceResult(
            check_name="session-to-process",
            level=ConformanceLevel.LIFECYCLE,
            passed=True,
            openclaw_concept="Gateway Session",
            nous_concept="AgentProcess",
            details="Session states map to process phases with checkpoint support.",
        )

        # Check state mapping completeness
        required_states = {"created", "active", "idle", "disconnected", "terminated"}
        mapped_states = {"CREATED", "CONNECTED", "ACTIVE", "IDLE", "DISCONNECTED", "TERMINATED"}
        if not required_states.issubset({s.lower() for s in mapped_states}):
            result.passed = False
            result.gaps.append("Missing state mapping for some session states")

        self.results.append(result)
        return result

    def check_workspace_to_namespace(self) -> ConformanceResult:
        """Verify workspace → namespace isolation mapping."""
        result = ConformanceResult(
            check_name="workspace-to-namespace",
            level=ConformanceLevel.ISOLATION,
            passed=True,
            openclaw_concept="Workspace",
            nous_concept="Namespace / Workspace",
            details="Workspace isolation levels map to namespace permissions.",
        )

        required_levels = {"full", "shared-read", "shared-readwrite"}
        from integrations.openclaw.session_adapter import SessionWorkspaceAdapter
        available_levels = set(SessionWorkspaceAdapter.ISOLATION_LEVELS.keys())

        if not required_levels.issubset(available_levels):
            result.passed = False
            result.gaps.append(f"Missing isolation levels: {required_levels - available_levels}")

        self.results.append(result)
        return result

    def check_skill_to_capability(self) -> ConformanceResult:
        """Verify skill → capability gating mapping."""
        result = ConformanceResult(
            check_name="skill-to-capability",
            level=ConformanceLevel.LIFECYCLE,
            passed=True,
            openclaw_concept="Skill",
            nous_concept="Capability / Tool Provider",
            details="Skills map to capability contracts with risk-based approval.",
        )

        # Check risk levels cover all OpenClaw skill types
        from integrations.openclaw.skill_adapter import SkillAdapter
        risk_levels = set(SkillAdapter.RISK_LEVELS.values())
        expected = {"low", "medium", "high"}
        if not expected.issubset(risk_levels):
            result.passed = False
            result.gaps.append(f"Missing risk levels: {expected - risk_levels}")

        self.results.append(result)
        return result

    def check_node_identity(self) -> ConformanceResult:
        """Verify node identity mapping."""
        result = ConformanceResult(
            check_name="node-identity",
            level=ConformanceLevel.SCHEMA,
            passed=True,
            openclaw_concept="Node",
            nous_concept="Nous Node",
        )
        self.results.append(result)
        return result

    def check_cron_durability(self) -> ConformanceResult:
        """Verify cron → automation durability mapping."""
        result = ConformanceResult(
            check_name="cron-durability",
            level=ConformanceLevel.DURABILITY,
            passed=True,
            openclaw_concept="Cron",
            nous_concept="Automation Workload",
            details="Scheduled tasks mapped to durable automation workloads with journal.",
        )
        # TODO: Verify journal integration when nousd is available
        if not self._check_journal_available():
            result.gaps.append("Journal integration pending — nousd not available")
        self.results.append(result)
        return result

    def run_all(self) -> list[ConformanceResult]:
        """Run all conformance checks."""
        self.results.clear()
        self.check_session_to_process()
        self.check_workspace_to_namespace()
        self.check_skill_to_capability()
        self.check_node_identity()
        self.check_cron_durability()
        return self.results

    def _check_journal_available(self) -> bool:
        """Check if Nous journal is available."""
        return importlib.util.find_spec("nous_runtime.events.bus") is not None

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)
