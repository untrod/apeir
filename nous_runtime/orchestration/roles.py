# -*- coding: utf-8 -*-
"""Dynamic Role Generation — generates agent roles from task requirements.

Roles are NOT fixed to Planner/Worker/Reviewer. They are dynamically
generated based on task type, complexity, risk, and required capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRole:
    """A dynamically generated agent role."""
    role_id: str = ""
    name: str = ""
    description: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    context_scope: str = "task"         # task, project, workspace, global
    output_contract: str = ""           # expected output format/type
    authority_level: str = "worker"     # worker, reviewer, arbiter, manager
    escalation_rules: list[str] = field(default_factory=list)
    can_delegate: bool = False
    requires_approval: bool = False


# Role templates

ROLE_TEMPLATES: dict[str, dict] = {
    "architect": {
        "required_capabilities": ["system_design", "architecture_planning"],
        "allowed_tools": ["diagram_generator", "doc_writer", "code_analyzer"],
        "authority_level": "manager",
        "context_scope": "project",
    },
    "researcher": {
        "required_capabilities": ["web_search", "synthesis", "source_evaluation"],
        "allowed_tools": ["web_search", "paper_reader", "note_taker"],
        "authority_level": "worker",
    },
    "literature_scout": {
        "required_capabilities": ["web_search", "paper_discovery", "citation_tracking"],
        "allowed_tools": ["web_search", "arxiv_search", "citation_graph"],
        "authority_level": "worker",
    },
    "data_engineer": {
        "required_capabilities": ["data_processing", "etl", "schema_design"],
        "allowed_tools": ["sql_runner", "data_transformer", "schema_validator"],
        "authority_level": "worker",
        "write_scope": "data_directory",
    },
    "code_worker": {
        "required_capabilities": ["code_generation", "code_editing"],
        "allowed_tools": ["file.read", "file.write", "code.execute", "test.run"],
        "authority_level": "worker",
        "write_scope": "workspace",
    },
    "test_engineer": {
        "required_capabilities": ["test_generation", "test_execution"],
        "allowed_tools": ["test.run", "coverage.check", "mutation.test"],
        "authority_level": "worker",
    },
    "security_reviewer": {
        "required_capabilities": ["security_audit", "vulnerability_detection"],
        "allowed_tools": ["code_analyzer", "dependency_scanner", "secret_scanner"],
        "authority_level": "reviewer",
        "requires_approval": True,
    },
    "evidence_verifier": {
        "required_capabilities": ["fact_checking", "source_verification"],
        "allowed_tools": ["web_search", "source_comparator", "claim_extractor"],
        "authority_level": "reviewer",
    },
    "adversarial_reviewer": {
        "required_capabilities": ["critical_analysis", "counterexample_generation"],
        "allowed_tools": ["code_analyzer", "logic_checker", "edge_case_generator"],
        "authority_level": "reviewer",
    },
    "integrator": {
        "required_capabilities": ["merge", "conflict_resolution", "synthesis"],
        "allowed_tools": ["merge_tool", "diff_viewer", "report_generator"],
        "authority_level": "manager",
    },
    "arbiter": {
        "required_capabilities": ["conflict_resolution", "decision_making", "evidence_evaluation"],
        "allowed_tools": ["comparator", "evidence_viewer", "decision_logger"],
        "authority_level": "arbiter",
    },
    "release_manager": {
        "required_capabilities": ["release_validation", "checklist_verification"],
        "allowed_tools": ["release_checker", "changelog_generator", "version_bumper"],
        "authority_level": "manager",
        "requires_approval": True,
    },
}


class RoleGenerator:
    """Generates dynamic agent roles based on task requirements."""

    def generate(self, task: dict[str, Any], task_graph: Any = None) -> list[AgentRole]:
        """Generate roles for a task."""
        task_type = str(task.get("task_type", "general"))
        complexity = str(task.get("complexity", "medium"))
        risk = str(task.get("risk_class", "low"))

        roles: list[AgentRole] = []

        if task_type in ("code_audit", "bug_fix", "code_refactor"):
            roles = self._code_roles(complexity, risk)
        elif task_type == "test_generation":
            roles = self._test_roles(complexity)
        elif task_type in ("research", "web_research"):
            roles = self._research_roles(complexity)
        elif task_type == "data_analysis":
            roles = self._data_roles(complexity)
        elif task_type in ("multi_node", "distributed"):
            roles = self._distributed_roles(complexity, risk)
        else:
            roles = self._default_roles(complexity)

        # Add reviewers for high-risk tasks
        if risk in ("high", "critical"):
            reviewer = self._make_role("security_reviewer", f"security_reviewer_{len(roles)}")
            roles.append(reviewer)
            if risk == "critical":
                arbiter = self._make_role("arbiter", f"arbiter_{len(roles)}")
                roles.append(arbiter)

        return roles

    def _code_roles(self, complexity: str, risk: str) -> list[AgentRole]:
        roles = [self._make_role("code_worker", "worker")]
        if complexity in ("high", "critical"):
            roles.append(self._make_role("architect", "architect"))
            roles.append(self._make_role("test_engineer", "tester"))
        return roles

    def _test_roles(self, complexity: str) -> list[AgentRole]:
        return [self._make_role("test_engineer", "tester")]

    def _research_roles(self, complexity: str) -> list[AgentRole]:
        roles = [self._make_role("researcher", "researcher")]
        if complexity in ("high", "critical"):
            roles.insert(0, self._make_role("literature_scout", "scout"))
            roles.append(self._make_role("evidence_verifier", "verifier"))
            roles.append(self._make_role("integrator", "integrator"))
        return roles

    def _data_roles(self, complexity: str) -> list[AgentRole]:
        return [self._make_role("data_engineer", "engineer")]

    def _distributed_roles(self, complexity: str, risk: str) -> list[AgentRole]:
        roles = [self._make_role("architect", "coordinator")]
        roles.append(self._make_role("code_worker", "worker_a"))
        roles.append(self._make_role("code_worker", "worker_b"))
        roles.append(self._make_role("integrator", "integrator"))
        return roles

    def _default_roles(self, complexity: str) -> list[AgentRole]:
        return [self._make_role("code_worker", "worker")]

    def _make_role(self, template_name: str, role_name: str) -> AgentRole:
        tmpl = ROLE_TEMPLATES.get(template_name, ROLE_TEMPLATES["code_worker"])
        return AgentRole(
            role_id=f"role_{role_name}",
            name=role_name,
            description=f"{template_name.replace('_', ' ').title()} agent",
            required_capabilities=list(tmpl.get("required_capabilities", [])),
            allowed_tools=list(tmpl.get("allowed_tools", [])),
            authority_level=str(tmpl.get("authority_level", "worker")),
            context_scope=str(tmpl.get("context_scope", "task")),
            requires_approval=bool(tmpl.get("requires_approval", False)),
        )
