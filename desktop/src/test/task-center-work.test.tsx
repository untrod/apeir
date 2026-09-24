import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TaskCenter } from "../components/TaskCenter";
import { entityStore, type Task } from "../store";


describe("Task Center Work projection", () => {
  it("shows durable Work plan and artifact progress", () => {
    const work: Task = {
      id: "work_desktop_projection",
      run_id: "work_desktop_projection",
      task_kind: "work",
      conversation_id: "conversation_1",
      name: "Fix the repository",
      status: "blocked",
      priority: "normal",
      model_id: "auto",
      plan_id: "plan_1",
      trace_id: "work_desktop_projection",
      plan_revision: 2,
      current_step: "verify",
      artifact_refs: ["sha256:" + "a".repeat(64)],
      steps: [
        {
          step_id: "verify",
          name: "Run targeted verification",
          status: "blocked",
          retry_count: 0,
          max_retries: 3,
        },
      ],
      progress_pct: 50,
      cancellation_requested: false,
      recoverable: true,
      schema_version: "1.0.0",
      created_at: "2026-09-24T00:00:00Z",
      updated_at: "2026-09-24T00:01:00Z",
    };
    entityStore.reconcile({ tasks: { [work.id]: work } });

    render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} />);

    expect(screen.getByText("Needs Input")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.getByText(/plan v2/)).toBeInTheDocument();
    expect(screen.getByText(/1 artifacts/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Fix the repository"));
    expect(screen.getByText("Run targeted verification")).toBeInTheDocument();
    expect(screen.getByText("verify")).toBeInTheDocument();
  });
});
