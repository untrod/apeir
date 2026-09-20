"""Controlled Code Assistant contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepositoryProfile:
    root: str
    languages: tuple[str, ...]
    toolchains: tuple[str, ...]
    files: tuple[str, ...]
    dependency_files: tuple[str, ...]


@dataclass(frozen=True)
class CodeChangePlan:
    objective: str
    allowed_files: tuple[str, ...]
    test_commands: tuple[tuple[str, ...], ...]
    static_analysis_commands: tuple[tuple[str, ...], ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeAssistantResult:
    ok: bool
    status: str
    changed_files: tuple[str, ...] = ()
    tests_selected: tuple[tuple[str, ...], ...] = ()
    errors: tuple[str, ...] = ()
    agent_result: dict[str, Any] = field(default_factory=dict)