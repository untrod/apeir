"""Controlled repository-change orchestration through CommandAgentAdapter."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Protocol

from nous_runtime.agents.external.models import AgentRunContext, AgentRunRequest, AgentRunResult
from nous_runtime.code_assistant.models import CodeAssistantResult, CodeChangePlan
from nous_runtime.code_assistant.repository import RepositoryAnalyzer


class CodingAgentAdapter(Protocol):
    def execute(self, request: AgentRunRequest, context: AgentRunContext) -> AgentRunResult: ...


class CodeAssistant:
    def __init__(self, workspace: str | Path, adapter: CodingAgentAdapter, *, isolated_workspace: bool = False, snapshot_limit_bytes: int = 50_000_000):
        self.workspace = Path(workspace).resolve()
        self.adapter = adapter
        self.isolated_workspace = isolated_workspace
        self.snapshot_limit_bytes = snapshot_limit_bytes
        self.analyzer = RepositoryAnalyzer()

    def plan(self, objective: str, *, allowed_files: tuple[str, ...], expected_artifacts: tuple[str, ...] = ()) -> CodeChangePlan:
        if not objective.strip():
            raise ValueError("code objective is required")
        normalized = tuple(sorted({self._relative(item, allow_nonexistent=True) for item in allowed_files}))
        if not normalized:
            raise ValueError("allowed_files is required")
        profile = self.analyzer.analyze(self.workspace)
        return CodeChangePlan(objective, normalized, self.analyzer.select_tests(profile), self.analyzer.select_static_analysis(profile), expected_artifacts, {"languages": list(profile.languages), "toolchains": list(profile.toolchains), "dependencies": list(profile.dependency_files)})

    def execute(self, plan: CodeChangePlan) -> CodeAssistantResult:
        if not self.isolated_workspace:
            return CodeAssistantResult(False, "denied", errors=("code changes require an isolated workspace",))
        before = self._snapshot()
        request = AgentRunRequest(objective=plan.objective, plan={"allowed_files": list(plan.allowed_files), "test_commands": [list(command) for command in plan.test_commands], "static_analysis_commands": [list(command) for command in plan.static_analysis_commands], "lifecycle": ["analyze", "change", "diff", "test", "review"]}, allowed_capabilities=("repository.read", "file.read", "file.write", "test.run", "static_analysis.run"), expected_artifacts=plan.expected_artifacts, approval_policy="ask_per_command")
        context = AgentRunContext(run_id=request.run_id, workspace_path=str(self.workspace), input_files=plan.allowed_files, environment={})
        try:
            result = self.adapter.execute(request, context)
        except Exception as exc:
            self._restore(before)
            return CodeAssistantResult(False, "failed", errors=(str(exc),))
        after = self._snapshot()
        changed = self._changed(before, after)
        denied = set(changed) - set(plan.allowed_files)
        if denied:
            self._restore(before)
            return CodeAssistantResult(False, "scope_violation", changed, plan.test_commands, ("agent changed files outside approved scope: " + ", ".join(sorted(denied)),), result.to_dict())
        if not result.ok:
            self._restore(before)
            return CodeAssistantResult(False, result.status.lower() or "failed", changed, plan.test_commands, tuple(result.errors), result.to_dict())
        return CodeAssistantResult(True, "completed", changed, plan.test_commands, (), result.to_dict())

    def rollback(self, snapshot: dict[str, bytes]) -> None:
        if not self.isolated_workspace:
            raise PermissionError("rollback requires an isolated workspace")
        self._restore(snapshot)

    def snapshot(self) -> dict[str, bytes]:
        return self._snapshot()

    def _snapshot(self) -> dict[str, bytes]:
        profile = self.analyzer.analyze(self.workspace)
        snapshot: dict[str, bytes] = {}
        total = 0
        for relative in profile.files:
            path = self.workspace / relative
            data = path.read_bytes()
            total += len(data)
            if total > self.snapshot_limit_bytes:
                raise RuntimeError("repository snapshot exceeds configured limit")
            snapshot[relative] = data
        return snapshot

    def _restore(self, snapshot: dict[str, bytes]) -> None:
        current = set(self.analyzer.analyze(self.workspace).files)
        for relative in current - set(snapshot):
            target = self.workspace / relative
            if target.is_file():
                target.unlink()
        for relative, data in snapshot.items():
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    @staticmethod
    def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> tuple[str, ...]:
        paths = set(before) | set(after)
        return tuple(sorted(path for path in paths if hashlib.sha256(before.get(path, b"")).digest() != hashlib.sha256(after.get(path, b"")).digest() or (path in before) != (path in after)))

    def _relative(self, value: str, *, allow_nonexistent: bool = False) -> str:
        relative = PurePosixPath(value.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("allowed file escapes workspace")
        if relative.parts[0] in {".git", ".nous"}:
            raise ValueError("repository metadata is outside code change scope")
        target = (self.workspace / Path(*relative.parts)).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("allowed file escapes workspace") from exc
        if not allow_nonexistent and not target.exists():
            raise FileNotFoundError(target)
        return relative.as_posix()