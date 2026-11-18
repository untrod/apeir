import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskCenter } from "../components/TaskCenter";
import { entityStore, type Task } from "../store";
import * as api from "../lib/api";


describe("Task Center Work projection", () => {
  beforeEach(() => entityStore.clearStore());
  afterEach(() => vi.restoreAllMocks());
  it("shows a rejected model response and resumes the original task only on click", async () => {
    const resume = vi.spyOn(api, "taskAction").mockResolvedValue({});
    const task: Task = {
      id: "work_rejected_model", task_kind: "work", name: "Explain this project",
      status: "waiting_user", model_id: "local/chosen-model", error: "MODEL_DECISION_INVALID: schema rejected",
      priority: "normal", steps: [], progress_pct: 0, recoverable: true,
      cancellation_requested: false, schema_version: "1.0.0",
      created_at: "2026-11-16T00:00:00Z", updated_at: "2026-11-16T00:00:00Z",
    };
    entityStore.reconcile({ tasks: { [task.id]: task } });
    render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByText(task.name));
    expect(screen.getByRole("status")).toHaveTextContent("Check the model settings");
    expect(screen.getByText(/local\/chosen-model/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(resume).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Resume original task" }));
    expect(resume).toHaveBeenCalledExactlyOnceWith("resume", task.id);
    expect(entityStore.getState().tasks[task.id]?.status).toBe("waiting_user");
  });
  it("opens the original approval and waits for an explicit task action", async () => {
    const task: Task = { id: "work_approval", task_kind: "work", name: "Original task",
      status: "waiting_user", priority: "normal", steps: [], progress_pct: 0, recoverable: true,
      cancellation_requested: false, schema_version: "1.0.0", created_at: "2026-11-16T00:00:00Z", updated_at: "2026-11-16T00:00:00Z" };
    const action = vi.spyOn(api, "taskAction").mockRejectedValue(new api.ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_original" }));
    const inspect = vi.fn();
    entityStore.reconcile({ tasks: { [task.id]: task } });
    render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} onApprovalClick={inspect} />);
    fireEvent.click(screen.getByText(task.name));
    fireEvent.click(screen.getByRole("button", { name: "Resume original task" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    expect(inspect).toHaveBeenCalledWith("apr_original");
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(entityStore.getState().tasks[task.id].status).toBe("waiting_user");
  });
  it.each([
    ["queued", "Active"], ["planning", "Active"], ["verifying", "Active"],
    ["recovering", "Active"], ["waiting_for_node", "Active"],
    ["completed_with_warnings", "Completed"], ["failed_verification", "Failed"],
  ] as const)("keeps %s visible in the %s filter", (status, label) => {
    const task: Task = {
      id: `task_filter_${status}`, name: `Filter ${status}`, status,
      priority: "normal", steps: [], progress_pct: 0,
      cancellation_requested: false, recoverable: false,
      schema_version: "1.0.0", created_at: "2026-10-11T00:00:00Z", updated_at: "2026-10-11T00:00:00Z",
    };
    entityStore.reconcile({ tasks: { [task.id]: task } });
    render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label} `) }));
    expect(screen.getByText(task.name)).toBeInTheDocument();
  });
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

    const onTaskClick = vi.fn();
    const onTraceClick = vi.fn();
    render(<TaskCenter onTaskClick={onTaskClick} onTraceClick={onTraceClick} />);

    expect(screen.getByText("Needs Input")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.getByText(/plan v2/)).toBeInTheDocument();
    expect(screen.getByText(/1 artifacts/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Fix the repository"));
    expect(screen.getByText("Run targeted verification")).toBeInTheDocument();
    expect(screen.getByText("verify")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View Work Activity" }));
    expect(onTaskClick).toHaveBeenCalledWith(work.id);
    expect(onTraceClick).not.toHaveBeenCalled();
  });
});
