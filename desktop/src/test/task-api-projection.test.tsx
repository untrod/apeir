import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { taskEntity } from "../lib/api";
import { entityStore } from "../store";
import { TaskCenter } from "../components/TaskCenter";

beforeEach(() => entityStore.clearStore());

it("adapts the original task_id-only HTTP shape without inventing steps, progress or recovery permission", () => {
  const task = taskEntity({ task_id: "original-runtime-task", name: "Inspect project", status: "RUNNING", priority: "HIGH", created_at: "2026-10-26T00:00:00Z" });
  expect(task.id).toBe("original-runtime-task");
  expect(task.status).toBe("running"); expect(task.priority).toBe("high");
  expect(task.steps_reported).toBe(false); expect(task.progress_reported).toBe(false); expect(task.recoverable).toBe(false);
  const restored = taskEntity(JSON.parse(JSON.stringify(task)));
  expect(restored.steps_reported).toBe(false); expect(restored.progress_reported).toBe(false);
  entityStore.upsertTasks([task]);
  const inspect = vi.fn();
  render(<TaskCenter onTaskClick={inspect} onTraceClick={vi.fn()} />);
  expect(screen.getByText(/Steps UNKNOWN/)).toBeVisible();
  expect(screen.getByText("UNKNOWN", { exact: true })).toBeVisible();
  fireEvent.click(screen.getByText("Inspect project", { exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "View Details" }));
  expect(inspect).toHaveBeenCalledWith("original-runtime-task");
});

it("preserves the complete durable Work projection and explicit zero progress", () => {
  const step = { step_id: "original-step", name: "Read", status: "blocked", retry_count: 0, max_retries: 0 };
  const task = taskEntity({ id: "original-work", task_id: "original-work", run_id: "original-run", task_kind: "work", status: "blocked", progress_pct: 0, steps: [step], recoverable: true, artifact_refs: ["sha256:" + "a".repeat(64)] });
  expect(task.run_id).toBe("original-run"); expect(task.steps).toEqual([step]);
  expect(task.progress_reported).toBe(true); expect(task.progress_pct).toBe(0); expect(task.recoverable).toBe(true);
  expect(task.artifact_refs).toHaveLength(1);
});

it.each([null, {}, { id: "one", task_id: "other" }, { task_id: "t", steps: [{}] }])("rejects missing/conflicting identities and malformed step records: %j", value => {
  expect(() => taskEntity(value)).toThrow(/task|identity|step/i);
  expect(entityStore.getState().tasks).toEqual({});
});

it("keeps unsupported states and nonfinite/out-of-range progress unknown, with no retry controls", () => {
  const task = taskEntity({ task_id: "uncertain-original", name: "Uncertain operation", status: "UNRECOGNIZED_RESULT", progress_pct: Infinity, recoverable: false });
  expect(task.status).toBe("unknown"); expect(task.progress_reported).toBe(false);
  entityStore.upsertTasks([task]);
  render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} />);
  fireEvent.click(screen.getByText("Uncertain operation", { exact: true }));
  expect(screen.getByText("unknown", { exact: true })).toBeVisible();
  expect(screen.queryByRole("button", { name: /Retry|Resume|Cancel|Pause/ })).not.toBeInTheDocument();
});
