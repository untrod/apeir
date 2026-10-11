import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeveloperWorkbench } from "../components/DeveloperWorkbench";
import {
  ApiError, approvalAction, fetchCapabilityAvailability, fetchDeveloperRuns,
  fetchRunEvents, fetchWorkbenchFile, fetchWorkbenchFiles, previewWorkbenchWrite,
  runWorkbenchProfile, setConfig, writeWorkbenchFile, fetchTrace, fetchTraceTimeline,
} from "../lib/api";

vi.mock("../lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("../lib/api")>(),
  approvalAction: vi.fn(), fetchCapabilityAvailability: vi.fn(), fetchDeveloperRuns: vi.fn(),
  fetchRunEvents: vi.fn(), fetchWorkbenchFile: vi.fn(), fetchWorkbenchFiles: vi.fn(),
  previewWorkbenchWrite: vi.fn(), runWorkbenchProfile: vi.fn(), writeWorkbenchFile: vi.fn(),
  fetchTrace: vi.fn(), fetchTraceTimeline: vi.fn(),
}));
vi.mock("../components/ChatView", () => ({ ChatView: ({ workspaceFile, readOnly, onTraceClick }: { workspaceFile?: { path: string; sha256: string }; readOnly: boolean; onTraceClick: (traceId: string) => void }) =>
  <div aria-label="Collaboration contract">{readOnly ? "read_only" : "agent"}{workspaceFile && <output>{JSON.stringify(workspaceFile)}</output>}<button onClick={() => onTraceClick("trace-original")}>View recorded Trace</button></div> }));

const before = "a".repeat(64), after = "b".repeat(64);
const change = { path: "a.py", exists: true, changed: true, before_sha256: before, after_sha256: after, size_bytes: 9, diff: "-old\n+new" };

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  setConfig({ url: "http://localhost:8770", token: "developer.fake.service" });
  vi.mocked(fetchWorkbenchFiles).mockResolvedValue({ workspace: "/workspace", path: ".", total: 2, truncated: false,
    files: ["a.py", "b.py"].map(path => ({ path, size_bytes: 4, modified_at: "2026-10-11", language: "python" })),
    profiles: [{ name: "pytest", available: true, executable: "pytest" }] });
  vi.mocked(fetchCapabilityAvailability).mockResolvedValue({ available: [], unavailable: [], summary: { available: 0, unavailable: 0, registered: 0 } });
  vi.mocked(fetchWorkbenchFile).mockImplementation(async path => ({ path, content: "old", sha256: before, size_bytes: 3, language: "python" }));
  vi.mocked(fetchDeveloperRuns).mockResolvedValue({ runs: [], total: 0 });
  vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "workbench-write-1", events: [], next_after_sequence: 0 });
  vi.mocked(previewWorkbenchWrite).mockResolvedValue(change);
  vi.mocked(writeWorkbenchFile).mockResolvedValue({ ...change, ok: true, run_id: "workbench-write-1", backup_path: "backup/a.py" });
  vi.mocked(approvalAction).mockResolvedValue({});
  vi.mocked(fetchTrace).mockResolvedValue({ trace_id: "trace-original", session_id: "", task_id: "task-original", root_span_id: "", total_duration_ms: 0, span_count: 0, has_errors: false, spans: [] });
  vi.mocked(fetchTraceTimeline).mockResolvedValue({ trace_id: "trace-original", spans: [], count: 0, global_statistics: {} });
});

async function edit() {
  render(<DeveloperWorkbench />);
  fireEvent.click(await screen.findByRole("button", { name: "a.py" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("old"));
  fireEvent.change(screen.getByRole("textbox", { name: "Code editor" }), { target: { value: "new" } });
}
async function requestSave() {
  fireEvent.click(screen.getByRole("button", { name: "Preview diff" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save atomically" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Save atomically" }));
}

describe("existing workspace developer panel", () => {
  it("keeps independent drafts, digests and previews while navigating file tabs", async () => {
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "Preview diff" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save atomically" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("old");
    expect(screen.getByRole("button", { name: "Save atomically" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run in sandbox" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "a.py" }));
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("new");
    expect(screen.getByRole("button", { name: "Save atomically" })).toBeEnabled();
    expect(fetchWorkbenchFile).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Save atomically" }));
    await waitFor(() => expect(writeWorkbenchFile).toHaveBeenCalledWith("a.py", "new", before));
    expect(screen.getByRole("tab", { name: "b.py" })).toBeInTheDocument();
  });

  it("protects an inactive draft until explicitly discarded and never persists its bytes", async () => {
    const protectedDraft = vi.fn(); render(<DeveloperWorkbench onDraftChange={protectedDraft} />);
    fireEvent.click(await screen.findByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("old"));
    fireEvent.change(screen.getByRole("textbox", { name: "Code editor" }), { target: { value: "private draft not for storage" } });
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    expect(protectedDraft).toHaveBeenLastCalledWith(true);
    const unloading = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unloading); expect(unloading.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close a.py" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Unsaved changes in a.py");
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("tab", { name: "a.py" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close a.py" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard draft and close" }));
    expect(screen.queryByRole("tab", { name: "a.py" })).not.toBeInTheDocument();
    await waitFor(() => expect(protectedDraft).toHaveBeenLastCalledWith(false));
    expect(JSON.stringify(localStorage)).not.toContain("private draft not for storage");
    expect(JSON.stringify(sessionStorage)).not.toContain("private draft not for storage");
    expect(writeWorkbenchFile).not.toHaveBeenCalled(); expect(runWorkbenchProfile).not.toHaveBeenCalled();
  });

  it("locks tab navigation while approval binds the original file and contents", async () => {
    vi.mocked(writeWorkbenchFile).mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_write" }));
    render(<DeveloperWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    fireEvent.click(screen.getByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("a.py"));
    fireEvent.change(screen.getByRole("textbox", { name: "Code editor" }), { target: { value: "new" } });
    await requestSave();
    await screen.findByRole("button", { name: "Approve once and save" });
    expect(screen.getByRole("tab", { name: "b.py" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close a.py" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and save" }));
    await waitFor(() => expect(writeWorkbenchFile).toHaveBeenCalledTimes(2));
    expect(vi.mocked(writeWorkbenchFile).mock.calls).toEqual([["a.py", "new", before], ["a.py", "new", before]]);
  });

  it("supports keyboard tab navigation without model calls or file writes", async () => {
    render(<DeveloperWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("a.py"));
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    fireEvent.keyDown(screen.getByRole("tab", { name: "b.py" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "a.py" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "a.py" })).toHaveFocus();
    expect(writeWorkbenchFile).not.toHaveBeenCalled(); expect(runWorkbenchProfile).not.toHaveBeenCalled();
  });

  it("refuses reopening cached file content under another Controller", async () => {
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    setConfig({ url: "http://another-controller:8770", token: "another.fake.service" });
    fireEvent.click(screen.getByRole("tab", { name: "a.py" }));
    expect(await screen.findByText(/Controller changed; reopen the original file tab/)).toBeInTheDocument();
    expect(fetchWorkbenchFile).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py");
    expect(writeWorkbenchFile).not.toHaveBeenCalled();
  });

  it("bounds file tabs and retains the original draft when another read fails", async () => {
    await edit();
    vi.mocked(fetchWorkbenchFile).mockRejectedValueOnce(new Error("File unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    expect(await screen.findByText("File unavailable")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("new");
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    for (let index = 0; index < 11; index++) fireEvent.click(screen.getByRole("button", { name: "New file" }));
    expect(screen.getAllByRole("tab")).toHaveLength(12);
    fireEvent.click(screen.getByRole("button", { name: "New file" }));
    expect(screen.getByText(/editor is limited to 12 tabs/)).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(12);
    fireEvent.click(screen.getByRole("tab", { name: "a.py" }));
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("new");
    expect(writeWorkbenchFile).not.toHaveBeenCalled();
  });

  it("clears the editor after its final tab closes and reloads changed files from Runtime", async () => {
    render(<DeveloperWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("old"));
    fireEvent.click(screen.getByRole("button", { name: "Close a.py" }));
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Code editor" })).toBeDisabled();
    vi.mocked(fetchWorkbenchFile).mockResolvedValueOnce({ path: "a.py", content: "changed outside editor", sha256: after, size_bytes: 22, language: "python" });
    fireEvent.click(screen.getByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("changed outside editor"));
    expect(fetchWorkbenchFile).toHaveBeenCalledTimes(2);
  });
  it("opens a Trace through the existing Trace inspector rather than querying a Run", async () => {
    render(<DeveloperWorkbench />);
    fireEvent.click(screen.getByRole("button", { name: "View recorded Trace" }));
    expect(await screen.findByRole("heading", { name: "Trace Timeline" })).toBeInTheDocument();
    await waitFor(() => expect(fetchTrace).toHaveBeenCalledWith("trace-original"));
    expect(fetchTraceTimeline).toHaveBeenCalledWith("trace-original");
    expect(fetchRunEvents).not.toHaveBeenCalled();
    expect(writeWorkbenchFile).not.toHaveBeenCalled(); expect(runWorkbenchProfile).not.toHaveBeenCalled();
  });
  it("refuses a Trace click after the original Controller changes", async () => {
    render(<DeveloperWorkbench />);
    await screen.findByRole("button", { name: "a.py" });
    setConfig({ url: "http://another-controller:8770", token: "another.fake.service" });
    fireEvent.click(screen.getByRole("button", { name: "View recorded Trace" }));
    expect(await screen.findByText(/Controller changed; review the original Trace again/)).toBeInTheDocument();
    expect(fetchTrace).not.toHaveBeenCalled(); expect(fetchTraceTimeline).not.toHaveBeenCalled();
    expect(fetchRunEvents).not.toHaveBeenCalled();
  });
  it("retains unsaved contents and path changes when switching files", async () => {
    await edit();
    fireEvent.click(screen.getByRole("button", { name: "b.py" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("b.py"));
    expect(fetchWorkbenchFile).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("tab", { name: "a.py" }));
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("new");
    fireEvent.change(screen.getByRole("textbox", { name: "Workspace file path" }), { target: { value: "other.py" } });
    expect(screen.getByText("Unsaved", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discuss saved file" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "b.py" }));
    fireEvent.click(screen.getByRole("tab", { name: "other.py" }));
    expect(screen.getByRole("textbox", { name: "Workspace file path" })).toHaveValue("other.py");
    expect(screen.getByRole("textbox", { name: "Code editor" })).toHaveValue("new");
  });

  it("requires preview and resumes exactly the original write after human approval", async () => {
    vi.mocked(writeWorkbenchFile).mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_write" }));
    await edit();
    expect(screen.getByRole("button", { name: "Save atomically" })).toBeDisabled();
    await requestSave();
    fireEvent.click(await screen.findByRole("button", { name: "Approve once and save" }));
    await waitFor(() => expect(writeWorkbenchFile).toHaveBeenCalledTimes(2));
    expect(approvalAction).toHaveBeenCalledWith("apr_write", "approve");
    expect(vi.mocked(writeWorkbenchFile).mock.calls[1]).toEqual(vi.mocked(writeWorkbenchFile).mock.calls[0]);
    expect(vi.mocked(writeWorkbenchFile).mock.calls[0]).toEqual(["a.py", "new", before]);
    await waitFor(() => expect(screen.queryByLabelText("Workbench approval")).not.toBeInTheDocument());
    expect(fetchRunEvents).toHaveBeenCalledWith("workbench-write-1");
  });

  it("denies without resuming and never repeats a lost-response save", async () => {
    vi.mocked(writeWorkbenchFile).mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_write" }));
    await edit(); await requestSave();
    fireEvent.click(await screen.findByRole("button", { name: "Deny original request" }));
    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_write", "deny"));
    expect(writeWorkbenchFile).toHaveBeenCalledTimes(1);
    vi.mocked(writeWorkbenchFile).mockRejectedValueOnce(new Error("Response lost"));
    await requestSave();
    expect(await screen.findByText(/Reload original state before repeating/)).toBeInTheDocument();
    expect(writeWorkbenchFile).toHaveBeenCalledTimes(2);
    expect(screen.queryByLabelText("Workbench approval")).not.toBeInTheDocument();
  });

  it("rejects resuming an approval on a different Controller", async () => {
    vi.mocked(writeWorkbenchFile).mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_write" }));
    await edit(); await requestSave();
    const approve = await screen.findByRole("button", { name: "Approve once and save" });
    setConfig({ url: "http://another-controller:8770", token: "another.fake.service" });
    fireEvent.click(approve);
    expect(await screen.findByText(/Controller changed; review original request again/)).toBeInTheDocument();
    expect(approvalAction).not.toHaveBeenCalled(); expect(writeWorkbenchFile).toHaveBeenCalledTimes(1);
  });

  it("shares only a saved file reference and persists only bounded layout preferences", async () => {
    render(<DeveloperWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "a.py" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Discuss saved file" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Discuss saved file" }));
    expect(screen.getByLabelText("Collaboration contract")).toHaveTextContent("read_only");
    expect(screen.getByLabelText("Collaboration contract")).toHaveTextContent(before);
    expect(screen.getByLabelText("Collaboration contract")).not.toHaveTextContent('"content"');
    fireEvent.change(screen.getByRole("textbox", { name: "Code editor" }), { target: { value: "private unsaved bytes" } });
    expect(screen.getByRole("button", { name: "Discuss saved file" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Editor font size"), { target: { value: "18" } });
    expect(JSON.parse(localStorage.getItem("apeir.developer.panel.v1")!)).toEqual({ fontSize: 18, conversation: true, activity: true });
    expect(localStorage.getItem("apeir.developer.panel.v1")).not.toContain("private unsaved bytes");
    expect(writeWorkbenchFile).not.toHaveBeenCalled(); expect(runWorkbenchProfile).not.toHaveBeenCalled();
  });

  it("reads persisted EventStream activity without inventing success", async () => {
    vi.mocked(fetchDeveloperRuns).mockResolvedValue({ runs: [{ run_id: "workbench-write-1", task_id: "workspace-write:a.py", state: "COMPLETED", current_step: "", total_steps: 1, completed_steps: 1, progress_pct: 100, created_at: "now", updated_at: "now", last_sequence: 7 }], total: 1 });
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "workbench-write-1", events: [{ event_id: "event-1", event_type: "file.changed", sequence: 7, timestamp: "now", payload: { path: "a.py", after_sha256: after } }], next_after_sequence: 7 });
    render(<DeveloperWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: /workspace-write:a.py/ }));
    expect(await screen.findByText(/7 · file.changed · now/)).toBeInTheDocument();
    expect(fetchRunEvents).toHaveBeenCalledWith("workbench-write-1"); expect(writeWorkbenchFile).not.toHaveBeenCalled();
  });

  it("reports UNKNOWN on execution response loss and does not retry", async () => {
    vi.mocked(runWorkbenchProfile).mockRejectedValue(new Error("Response lost"));
    render(<DeveloperWorkbench />);
    await screen.findByRole("button", { name: "a.py" });
    fireEvent.click(screen.getByRole("button", { name: "Run in sandbox" }));
    expect(await screen.findByText(/Outcome may be UNKNOWN/)).toBeInTheDocument();
    expect(runWorkbenchProfile).toHaveBeenCalledTimes(1); expect(runWorkbenchProfile).toHaveBeenCalledWith("pytest", "tests", 120);
  });

  it("inspects a persisted non-workbench Run without calling a model or mutating files", async () => {
    vi.mocked(fetchDeveloperRuns).mockResolvedValue({ runs: [{ run_id: "gateway-original", task_id: "task-original", state: "COMPLETED", current_step: "", total_steps: 0, completed_steps: 0, progress_pct: 0, created_at: "now", updated_at: "now", last_sequence: 3 }], total: 1 });
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "gateway-original", events: [], next_after_sequence: 0 });
    render(<DeveloperWorkbench />);
    await screen.findByRole("option", { name: "gateway-original · COMPLETED" });
    fireEvent.change(screen.getByRole("combobox", { name: "Recorded input Run" }), { target: { value: "gateway-original" } });
    expect(await screen.findByText(/no recorded model input/)).toBeInTheDocument();
    expect(fetchRunEvents).toHaveBeenCalledWith("gateway-original", 0);
    expect(writeWorkbenchFile).not.toHaveBeenCalled(); expect(runWorkbenchProfile).not.toHaveBeenCalled();
  });
});
