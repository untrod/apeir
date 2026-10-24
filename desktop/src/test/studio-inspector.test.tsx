import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StudioPanel } from "../components/studio/StudioPanels";
import { entityStore, type Task } from "../store";
import { TaskCenter } from "../components/TaskCenter";
import * as runtimeApi from "../lib/api";
import { toast } from "../components/Toast";

afterEach(() => { sessionStorage.clear(); entityStore.clearStore(); });
it("opens the original task in the existing Inspector instead of losing its identity", () => {
  entityStore.clearStore();
  const task: Task = { id: "original-studio-work", run_id: "original-studio-work", trace_id: "original-studio-work", task_kind: "work", name: "Inspect original Work", status: "blocked", priority: "normal", steps: [], progress_pct: 0, cancellation_requested: false, recoverable: true, schema_version: "1.0.0", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" };
  entityStore.reconcile({ tasks: { [task.id]: task } });
  const inspect = vi.fn(); const open = vi.fn();
  render(<StudioPanel locale="en" isVisible={() => true} updateConfig={vi.fn()} saveLayout={vi.fn()} type="tasks" inspect={inspect} open={open} onDraftChange={vi.fn()} onDraftSnapshot={vi.fn()} />);
  fireEvent.click(screen.getByText(task.name));
  fireEvent.click(screen.getByRole("button", { name: "View Work Activity" }));
  expect(inspect).toHaveBeenCalledWith({ kind: "task", taskId: task.id });
  expect(open).not.toHaveBeenCalled();
});

it.each([false, true])("connects conversation navigation only when this view provides a consumer: %s", connected => {
  entityStore.clearStore();
  const task: Task = { id: "original-task", conversation_id: "original-conversation", name: "Conversation-bound task", status: "completed", priority: "normal", steps: [], progress_pct: 100, cancellation_requested: false, recoverable: false, schema_version: "1.0.0", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" };
  entityStore.reconcile({ tasks: { [task.id]: task } });
  const navigate = vi.fn();
  render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} onConversationClick={connected ? navigate : undefined} />);
  fireEvent.click(screen.getByText(task.name));
  const button = screen.getByRole("button", { name: "Open Conversation" });
  if (connected) { fireEvent.click(button); expect(navigate).toHaveBeenCalledWith(task.conversation_id); }
  else { expect(button).toBeDisabled(); expect(button).toHaveAttribute("title", "Conversation navigation is not connected in this view."); }
});

it("does not publish an old action acknowledgement after a Controller change", async () => {
  runtimeApi.setConfig({ url: "http://127.0.0.1:8770", token: "fake-studio-task-a" });
  const task: Task = { id: "cancel-original-task", name: "Original cancellable task", status: "running", priority: "normal", steps: [], progress_pct: 0, cancellation_requested: false, recoverable: true, schema_version: "1.0.0", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" };
  entityStore.reconcile({ tasks: { [task.id]: task } });
  let release!: (value: unknown) => void;
  const action = vi.spyOn(runtimeApi, "taskAction").mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const acknowledged = vi.spyOn(toast, "success");
  render(<TaskCenter onTaskClick={vi.fn()} onTraceClick={vi.fn()} />);
  fireEvent.click(screen.getByText(task.name)); fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(action).toHaveBeenCalledWith("cancel", task.id);
  act(() => runtimeApi.setConfig({ url: "http://127.0.0.1:9770", token: "fake-studio-task-b" }));
  await act(async () => release({ status: "requested" }));
  expect(acknowledged).not.toHaveBeenCalled(); expect(action).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(task.name)).not.toBeInTheDocument();
});
