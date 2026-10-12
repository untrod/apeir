import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceProposals } from "../components/WorkspaceProposals";
import { approvalAction, fetchWorkspaceProposal, fetchWorkspaceProposals, prepareWorkspaceProposal, setConfig, workspaceProposalAction, type WorkspaceProposal } from "../lib/api";

vi.mock("../lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("../lib/api")>(),
  approvalAction: vi.fn(), fetchWorkspaceProposal: vi.fn(), fetchWorkspaceProposals: vi.fn(),
  prepareWorkspaceProposal: vi.fn(), workspaceProposalAction: vi.fn(),
}));

const original: WorkspaceProposal = {
  proposal_id: "original-workflow", work_id: "original-operation", state: "PROPOSED", workflow_state: "waiting_approval",
  authorization_id: "original-authorization", approval_request_id: "original-approval", approval_status: "PENDING",
  approval_required: true, manifest_ref: "sha256:manifest", resource_id: "workspace:original", applied: false,
  recovery_required: false, execution_scope: "runtime-service", kernel_traversed: false, verification: {},
  file_count: 1, total_size_bytes: 3, files: [{ path: "a.py", diff: "-old\n+new", expected_exists: true,
    before_sha256: "before", after_sha256: "after", before_ref: "sha256:before", after_ref: "sha256:after",
    changed: true, size_bytes: 3, current_exists: true, current_sha256: "before" }],
};
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); setConfig({ url: "http://localhost:8770", token: "fake.service" });
  vi.mocked(fetchWorkspaceProposals).mockResolvedValue({ proposals: [original], total: 1 });
  vi.mocked(fetchWorkspaceProposal).mockResolvedValue(original);
  vi.mocked(approvalAction).mockResolvedValue({});
});
async function inspect() {
  fireEvent.click(await screen.findByRole("button", { name: "original-workflow · PROPOSED" }));
  await screen.findByRole("button", { name: "Approve once and apply original" });
}
it("approves and applies only the inspected original operation, then reports recorded MATCH", async () => {
  const applied = { ...original, state: "APPLIED", applied: true, approval_required: false, approval_status: "APPROVED", verification: { verdict: "MATCH" } };
  vi.mocked(workspaceProposalAction).mockResolvedValue(applied);
  const onApplied = vi.fn(); render(<WorkspaceProposals onApplied={onApplied} />); await inspect();
  fireEvent.click(screen.getByRole("button", { name: "Approve once and apply original" }));
  await waitFor(() => expect(onApplied).toHaveBeenCalledWith(applied));
  expect(approvalAction).toHaveBeenCalledWith("original-approval", "approve");
  expect(workspaceProposalAction).toHaveBeenCalledWith("original-workflow", "apply");
  expect(prepareWorkspaceProposal).not.toHaveBeenCalled();
});
it("Deny reads the original result without applying or creating another operation", async () => {
  render(<WorkspaceProposals />); await inspect();
  fireEvent.click(screen.getByRole("button", { name: "Deny original proposal" }));
  await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("original-approval", "deny"));
  expect(workspaceProposalAction).not.toHaveBeenCalled(); expect(prepareWorkspaceProposal).not.toHaveBeenCalled();
});
it("lost response retains the original ID and never automatically retries a write", async () => {
  vi.mocked(workspaceProposalAction).mockRejectedValue(new Error("response lost"));
  render(<WorkspaceProposals />); await inspect(); fireEvent.click(screen.getByRole("button", { name: "Approve once and apply original" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Inspect or reconcile this proposal");
  expect(workspaceProposalAction).toHaveBeenCalledTimes(1); expect(prepareWorkspaceProposal).not.toHaveBeenCalled();
});
it("UNKNOWN exposes reconciliation of the same original ID and cannot emit success", async () => {
  const unknown = { ...original, state: "UNKNOWN", approval_required: false, recovery_required: true, verification: { verdict: "UNKNOWN" } };
  vi.mocked(fetchWorkspaceProposal).mockResolvedValue(unknown); vi.mocked(workspaceProposalAction).mockResolvedValue(unknown);
  const onApplied = vi.fn(); render(<WorkspaceProposals focusProposalId="original-workflow" onApplied={onApplied} />);
  fireEvent.click(await screen.findByRole("button", { name: "Reconcile original file evidence" }));
  await waitFor(() => expect(workspaceProposalAction).toHaveBeenCalledWith("original-workflow", "reconcile"));
  expect(onApplied).not.toHaveBeenCalled(); expect(approvalAction).not.toHaveBeenCalled();
});
it("a changed Controller after approval prevents submission to another Controller", async () => {
  vi.mocked(approvalAction).mockImplementation(async () => { setConfig({ url: "http://different-controller", token: "different.fake" }); return {}; });
  render(<WorkspaceProposals />); await inspect(); fireEvent.click(screen.getByRole("button", { name: "Approve once and apply original" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Controller changed");
  expect(workspaceProposalAction).not.toHaveBeenCalled(); expect(prepareWorkspaceProposal).not.toHaveBeenCalled();
});
it("an applied flag with MISMATCH cannot notify successful effect verification", async () => {
  vi.mocked(workspaceProposalAction).mockResolvedValue({ ...original, applied: true, verification: { verdict: "MISMATCH" } });
  const onApplied = vi.fn(); render(<WorkspaceProposals onApplied={onApplied} />); await inspect();
  fireEvent.click(screen.getByRole("button", { name: "Approve once and apply original" }));
  await waitFor(() => expect(workspaceProposalAction).toHaveBeenCalledTimes(1)); expect(onApplied).not.toHaveBeenCalled();
});
