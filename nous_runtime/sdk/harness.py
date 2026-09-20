"""SDK 2.0 test harness for agents and runtime requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.runtime.orchestrator import RuntimeOrchestrator
from nous_runtime.runtime.request import RuntimeRequest


@dataclass
class AgentTestHarness:
    workspace_root: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)

    def run_request(self, text: str, *, workspace: str = "", session: str = "sdk-test") -> dict[str, Any]:
        response = RuntimeOrchestrator(workspace_root=self.workspace_root).run(
            RuntimeRequest(text, workspace=workspace, session=session, user_id="sdk")
        )
        data = response.to_dict()
        self.results.append(data)
        return data

    def assert_success(self, text: str, *, workspace: str = "") -> dict[str, Any]:
        data = self.run_request(text, workspace=workspace)
        if data["status"] != "ok":
            raise AssertionError(f"runtime request failed: {data['status']} {data['message']}")
        return data
