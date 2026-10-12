import { useCallback, useEffect, useRef, useState } from "react";

import { btnPrimary, btnSecondary } from "../design";
import {
  approvalAction, fetchWorkspaceProposal, fetchWorkspaceProposals, getConfig,
  prepareWorkspaceProposal, workspaceProposalAction,
  type WorkspaceProposal, type WorkspaceProposalInput,
} from "../lib/api";
import { errorMessage } from "../lib/format";

export function WorkspaceProposals({ drafts = [], disabled = false, onApplied, onBusyChange, focusProposalId = "" }: {
  drafts?: WorkspaceProposalInput[];
  disabled?: boolean;
  onApplied?: (proposal: WorkspaceProposal) => void | Promise<void>;
  onBusyChange?: (busy: boolean) => void;
  focusProposalId?: string;
}) {
  const [records, setRecords] = useState<WorkspaceProposal[]>([]);
  const [selected, setSelected] = useState<WorkspaceProposal | null>(null);
  const [controller, setController] = useState(getConfig().url);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  const assertController = (original: string) => {
    if (getConfig().url !== original) throw new Error("Controller changed; inspect the original proposal before continuing.");
  };
  const refresh = useCallback(async () => {
    const original = getConfig().url;
    const read = ++generation.current;
    const result = await fetchWorkspaceProposals();
    if (getConfig().url !== original) throw new Error("Controller changed; reopen the original proposals.");
    if (read !== generation.current) return;
    setRecords(result.proposals); setController(original);
  }, []);
  useEffect(() => { void refresh().catch(cause => setError(errorMessage(cause, "Proposals are unavailable."))); }, [refresh]);
  useEffect(() => {
    if (!focusProposalId) return;
    let active = true;
    const original = getConfig().url;
    void fetchWorkspaceProposal(focusProposalId).then(result => {
      if (!active) return;
      if (getConfig().url !== original) throw new Error("Controller changed; inspect the original proposal.");
      setController(original); setSelected(result); return refresh();
    }).catch(cause => { if (active) setError(errorMessage(cause, "Original model proposal is unavailable.")); });
    return () => { active = false; };
  }, [focusProposalId, refresh]);

  const inspect = async (record: WorkspaceProposal) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      assertController(controller);
      const result = await fetchWorkspaceProposal(record.proposal_id);
      assertController(controller); setSelected(result);
    } catch (cause) { setError(errorMessage(cause, "Original proposal could not be read.")); }
    finally { setBusy(false); }
  };

  const prepare = async (files: WorkspaceProposalInput[]) => {
    if (busy || disabled || !files.length) return;
    const original = getConfig().url;
    setBusy(true); setError("");
    try {
      const result = await prepareWorkspaceProposal(files, "Reviewed workspace edits");
      assertController(original); setController(original); setSelected(result);
      await refresh();
    } catch (cause) { setError(errorMessage(cause, "Proposal could not be prepared. No automatic retry.")); }
    finally { setBusy(false); }
  };

  const act = async (action: "approve" | "deny" | "reconcile" | "apply") => {
    if (!selected || busy || disabled) return;
    const original = controller;
    const proposal = selected;
    setBusy(true); setError("");
    try {
      assertController(original);
      if (action === "approve" || action === "deny") {
        await approvalAction(proposal.approval_request_id, action);
        assertController(original);
      }
      const result = action === "deny" ? await fetchWorkspaceProposal(proposal.proposal_id)
        : await workspaceProposalAction(proposal.proposal_id, action === "reconcile" ? "reconcile" : "apply");
      assertController(original); setSelected(result); await refresh();
      if (result.applied && result.verification.verdict === "MATCH") await onApplied?.(result);
    } catch (cause) {
      setError(`${errorMessage(cause, "Original action could not be confirmed.")} Inspect or reconcile this proposal; do not create a replacement to repeat an uncertain write.`);
    } finally { setBusy(false); }
  };

  return <section aria-label="Workspace change proposals">
    <h3>Change proposals / 变更提案</h3>
    <p>Review exact files and versions. Human approval resumes the original Workflow; installation and model output grant no authority.</p>
    <div className="developer-activity">
      <button style={btnSecondary} disabled={busy} onClick={() => void refresh().catch(cause => setError(errorMessage(cause, "Proposals are unavailable.")))}>Refresh proposals</button>
      <button style={btnPrimary} disabled={busy || disabled || !drafts.length} onClick={() => void prepare(drafts)}>Review {drafts.length} draft files</button>
      {drafts.length > 1 && <button style={btnSecondary} disabled={busy || disabled} onClick={() => void prepare([drafts[0]])}>Review {drafts[0].path} only</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {!records.length && !error && <p>No persisted proposals.</p>}
    <div className="developer-activity">{records.map(record => <button key={record.proposal_id} style={btnSecondary} disabled={busy} onClick={() => void inspect(record)}>{record.proposal_id} · {record.state}</button>)}</div>
    {selected && <div>
      <p>{selected.proposal_id} · {selected.state} · Workflow {selected.workflow_state}</p>
      <p>Scope: {selected.execution_scope} · Kernel traversed: {String(selected.kernel_traversed)} · File verification: {selected.verification.verdict || "UNKNOWN"}</p>
      {selected.error && <p role="alert">{selected.error}</p>}
      {selected.files.map(file => <details key={file.path} open><summary>{file.path} · {file.before_sha256 || "new file"} → {file.after_sha256}</summary><p>Current file: {file.current_exists === null ? "UNKNOWN" : file.current_exists ? file.current_sha256 : "absent"}</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 280, overflow: "auto" }}>{file.diff || "No content change."}</pre></details>)}
      {selected.approval_required && selected.workflow_state === "waiting_approval" && <div className="developer-activity">
        <button style={btnPrimary} disabled={busy || disabled} onClick={() => void act("approve")}>Approve once and apply original</button>
        <button style={btnSecondary} disabled={busy || disabled} onClick={() => void act("deny")}>Deny original proposal</button>
      </div>}
      {!selected.approval_required && selected.state === "PROPOSED" && selected.approval_status === "APPROVED" && <button style={btnPrimary} disabled={busy || disabled} onClick={() => void act("apply")}>Resume original approved proposal</button>}
      {selected.recovery_required && <button style={btnSecondary} disabled={busy || disabled} onClick={() => void act("reconcile")}>Reconcile original file evidence</button>}
      <details><summary>Evidence identifiers</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify({ work_id: selected.work_id, authorization_id: selected.authorization_id, approval_request_id: selected.approval_request_id, resource_id: selected.resource_id, manifest_ref: selected.manifest_ref, ...selected.verification }, null, 2)}</pre></details>
      <p>Fresh file hashes verify file contents. They do not prove tests passed or a physical device effect. Multi-file writes are recovered from their original journal, not a universal atomic rollback.</p>
    </div>}
  </section>;
}
