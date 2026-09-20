import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckpointHealth } from "../components/Inspector";
import { fetchInspectorCheckpoints } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchInspectorCheckpoints: vi.fn(),
}));

describe("checkpoint inspector", () => {
  beforeEach(() => {
    vi.mocked(fetchInspectorCheckpoints).mockResolvedValue({
      status: "healthy",
      reason: "",
      workspace_available: true,
      database: {
        filename: "agent-checkpoints.db",
        exists: true,
        size_bytes: 4096,
      },
      integrity: {
        quick_check: "ok",
        messages: ["ok"],
        total: 3,
        valid: 3,
        invalid: 0,
      },
      tasks: 2,
      latest: [
        {
          checkpoint_id: "checkpoint-1",
          task_id: "task-a",
          timestamp: "2026-08-28T00:00:00Z",
          kind: "agent_execution",
          run_id: "run-a",
          agent_id: "agent-a",
        },
      ],
      invalid: [],
      retention: {
        policy: "keep_latest_per_task",
        keep_latest_per_task: 20,
        candidate_count: 1,
        protected_count: 2,
        invalid_excluded: 0,
        plan_digest: "a".repeat(64),
        requires_governed_apply: true,
      },
    });
  });

  it("renders integrity totals and a non-destructive retention preview", async () => {
    render(<CheckpointHealth />);

    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Stored").parentElement).toHaveTextContent("3");
    expect(screen.getByText("Invalid").parentElement).toHaveTextContent("0");
    expect(screen.getByText(/keep 20 per task/)).toHaveTextContent("1 removable");
    expect(screen.getByText("task-a")).toBeInTheDocument();
    expect(screen.queryByText(/must_not_leak/)).not.toBeInTheDocument();
    expect(screen.getByText(/governed API approval/)).toBeInTheDocument();
  });
});
