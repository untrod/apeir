import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { btnPrimary, btnSecondary, colors, radius, space, typo } from "../design";
import {
  ApiError, approvalAction, captureRuntimeConnection, getConfig, fetchDeveloperRuns, fetchRunEvents,
  type DeveloperRun,
  fetchCapabilityAvailability,
  fetchWorkbenchFile,
  fetchWorkbenchFiles,
  previewWorkbenchWrite,
  runWorkbenchProfile,
  searchWorkbench,
  writeWorkbenchFile,
  type CapabilityAvailability,
  type WorkbenchFileEntry,
  type WorkbenchListing,
  type WorkbenchPreview,
  type WorkbenchRunResult,
  type WorkbenchWriteResult,
} from "../lib/api";
import { errorMessage } from "../lib/format";
import { ChatView } from "./ChatView";
import { ContextInspector } from "./ContextInspector";
import { DetailDrawer } from "./DetailDrawer";
import { WorkspaceProposals } from "./WorkspaceProposals";
import type { WorkspaceProposal } from "../lib/api";
import type { RuntimeEventEnvelope } from "../store";
import "./DeveloperWorkbench.css";

type PanelPreferences = { fontSize: number; conversation: boolean; activity: boolean };
const preferenceKey = "apeir.developer.panel.v1";
function preferences(): PanelPreferences {
  try {
    const saved = JSON.parse(localStorage.getItem(preferenceKey) || "null");
    return { fontSize: [12, 14, 16, 18].includes(saved?.fontSize) ? saved.fontSize : 14,
      conversation: saved?.conversation !== false, activity: saved?.activity !== false };
  } catch { return { fontSize: 14, conversation: true, activity: true }; }
}
type PendingAction = { approvalId: string; controller: string } & (
  { kind: "save"; path: string; content: string; sha256: string }
  | { kind: "run"; profile: string; target: string }
);
type EditorTab = {
  id: number; controller: string; path: string; content: string;
  loadedPath: string; loadedContent: string; sha256: string;
  preview: WorkbenchPreview | null; writeResult: WorkbenchWriteResult | null;
};
const maxEditorTabs = 12;
const tabIsDirty = (tab: EditorTab) => tab.path !== tab.loadedPath || tab.content !== tab.loadedContent;

const panel: React.CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.lg,
};

const input: React.CSSProperties = {
  border: `1px solid ${colors.border}`,
  borderRadius: radius.md,
  padding: `${space.sm} ${space.md}`,
  background: colors.surface,
  color: colors.text,
  fontFamily: typo.font,
  fontSize: typo.sm,
};

export type WorkbenchDraft = { path: string; content: string; originalSha256: string };
export function DeveloperWorkbench({ onOpenEnvironments, onDraftChange, onDraftSnapshot, embeddedConversation = true }: {
  onOpenEnvironments?: () => void; onDraftChange?: (protectedDraft: boolean) => void;
  onDraftSnapshot?: (drafts: WorkbenchDraft[]) => void; embeddedConversation?: boolean;
}) {
  const [connection] = useState(captureRuntimeConnection);
  const active = useRef(true);
  const assertConnection = useCallback(() => {
    connection();
    if (!active.current) throw new Error("Workspace closed; inspect the original operation before continuing.");
  }, [connection]);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const [listing, setListing] = useState<WorkbenchListing | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityAvailability | null>(null);
  const [filePath, setFilePath] = useState("");
  const [content, setContent] = useState("");
  const [loadedContent, setLoadedContent] = useState("");
  const [loadedPath, setLoadedPath] = useState("");
  const [loadedSha256, setLoadedSha256] = useState("");
  const [preview, setPreview] = useState<WorkbenchPreview | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Array<{ path: string; line: number; text: string }>>([]);
  const [profile, setProfile] = useState("pytest");
  const [runTarget, setRunTarget] = useState("tests");
  const [runResult, setRunResult] = useState<WorkbenchRunResult | null>(null);
  const [writeResult, setWriteResult] = useState<WorkbenchWriteResult | null>(null);
  const [operationBusy, setBusy] = useState(false);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [collaborationMode, setCollaborationMode] = useState<"ask" | "edit">("ask");
  const [focusProposalId, setFocusProposalId] = useState("");
  const busy = operationBusy || proposalBusy;
  const [error, setError] = useState("");
  const [layout, setLayout] = useState(preferences);
  const [runs, setRuns] = useState<DeveloperRun[]>([]);
  const [contextRuns, setContextRuns] = useState<DeveloperRun[]>([]);
  const [runController, setRunController] = useState(getConfig().url);
  const [contextView, setContextView] = useState<{ runId: string; controller: string } | null>(null);
  const [traceView, setTraceView] = useState<{ traceId: string; controller: string } | null>(null);
  const [events, setEvents] = useState<Partial<RuntimeEventEnvelope>[]>([]);
  const [selectedRun, setSelectedRun] = useState("");
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [reference, setReference] = useState<{ path: string; sha256: string; controller: string }>();
  const [loadedController, setLoadedController] = useState(getConfig().url);
  const eventRead = useRef(0);
  const [conversationId, setConversationId] = useState<string>();
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTab, setActiveTab] = useState<number | null>(null);
  const tabSequence = useRef(0);
  const [closeTarget, setCloseTarget] = useState<number | null>(null);
  useEffect(() => { try { localStorage.setItem(preferenceKey, JSON.stringify(layout)); } catch { /* Preferences are optional. */ } }, [layout]);

  const refresh = useCallback(async () => {
    assertConnection();
    const controller = getConfig().url;
    const [filesResult, capabilityResult, runRecords] = await Promise.allSettled([
      fetchWorkbenchFiles(),
      fetchCapabilityAvailability(), fetchDeveloperRuns(),
    ]);
    assertConnection();
    if (controller !== getConfig().url) throw new Error("Controller changed; reopen the original workspace.");
    if (runRecords.status === "fulfilled") {
      setRuns(runRecords.value.runs.filter(item => item.run_id.startsWith("workbench-")));
      setContextRuns(runRecords.value.runs); setRunController(controller);
    } else setContextRuns([]);
    if (filesResult.status === "fulfilled") setListing(filesResult.value);
    if (capabilityResult.status === "fulfilled") setCapabilities(capabilityResult.value);
    const failure = [filesResult, capabilityResult, runRecords].find((item) => item.status === "rejected");
    if (failure?.status === "rejected") setError(errorMessage(failure.reason, "Workbench data is unavailable."));
  }, [assertConnection]);

  useEffect(() => { void refresh().catch(cause => setError(errorMessage(cause, "Workspace unavailable."))); }, [refresh]);

  const dirty = content !== loadedContent || filePath !== loadedPath;
  const protectedDraft = dirty || tabs.some(tab => tab.id !== activeTab && tabIsDirty(tab));
  useEffect(() => { onDraftChange?.(protectedDraft || !!pending || proposalBusy); }, [protectedDraft, pending, proposalBusy, onDraftChange]);
  useEffect(() => {
    onDraftSnapshot?.([
      ...tabs.filter(tab => tab.id !== activeTab && tabIsDirty(tab)).map(tab => ({ path: tab.path, content: tab.content, originalSha256: tab.sha256 })),
      ...(dirty ? [{ path: filePath, content, originalSha256: loadedSha256 }] : []),
    ]);
  }, [tabs, activeTab, dirty, filePath, content, loadedSha256, onDraftSnapshot]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (protectedDraft || pending || proposalBusy) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [protectedDraft, pending, proposalBusy]);
  const availableProfiles = useMemo(
    () => (listing?.profiles || []).filter((item) => item.available),
    [listing],
  );

  const showEvents = async (runId: string) => {
    const read = ++eventRead.current;
    const controller = getConfig().url; setSelectedRun(runId); setEvents([]);
    try {
      assertConnection();
      const result = await fetchRunEvents(runId);
      assertConnection();
      if (controller !== getConfig().url) throw new Error("Controller changed; reopen original evidence.");
      if (read === eventRead.current) setEvents(result.events);
    } catch (cause) { if (read === eventRead.current) setError(errorMessage(cause, "Persisted activity is unavailable.")); }
  };

  const showTrace = (traceId: string) => {
    if (loadedController !== getConfig().url) {
      setError("Controller changed; review the original Trace again.");
      return;
    }
    setTraceView({ traceId, controller: loadedController });
  };

  const currentTab = (): EditorTab => ({ id: activeTab ?? 0, controller: loadedController,
    path: filePath, content, loadedPath, loadedContent, sha256: loadedSha256, preview, writeResult });

  const rememberTab = (next: EditorTab) => {
    const original = activeTab === null ? null : currentTab();
    setTabs(value => {
      const retained = value.map(tab => tab.id === original?.id ? original : tab);
      return retained.some(tab => tab.id === next.id) ? retained : [...retained, next];
    });
    setActiveTab(next.id);
  };

  const restoreTab = (tab: EditorTab) => {
    setFilePath(tab.path); setLoadedPath(tab.loadedPath); setContent(tab.content);
    setLoadedContent(tab.loadedContent); setLoadedSha256(tab.sha256);
    setLoadedController(tab.controller); setPreview(tab.preview); setWriteResult(tab.writeResult);
    setReference(undefined); setError("");
    if (profile === "python" || profile === "python-compile" || profile === "node") setRunTarget(tab.path);
  };

  const switchTab = (id: number) => {
    if (busy || pending || closeTarget !== null || id === activeTab) return;
    const tab = tabs.find(item => item.id === id);
    if (!tab) return;
    if (tab.controller !== getConfig().url) { setError("Controller changed; reopen the original file tab."); return; }
    rememberTab(tab); restoreTab(tab);
  };

  const loadFile = async (path: string) => {
    if (!path || busy || pending || closeTarget !== null) return;
    const existing = tabs.find(tab => tab.controller === getConfig().url && (tab.path === path || tab.loadedPath === path));
    if (existing) { switchTab(existing.id); return; }
    if (tabs.length >= maxEditorTabs) { setError("Close a file tab before opening another; the editor is limited to 12 tabs."); return; }
    const controller = getConfig().url;
    setBusy(true); setError("");
    try {
      assertConnection();
      const file = await fetchWorkbenchFile(path);
      assertConnection();
      if (controller !== getConfig().url) throw new Error("Controller changed; reload the original file.");
      const tab: EditorTab = { id: ++tabSequence.current, controller, path: file.path,
        content: file.content, loadedPath: file.path, loadedContent: file.content,
        sha256: file.sha256, preview: null, writeResult: null };
      rememberTab(tab); restoreTab(tab);
    } catch (cause) {
      setError(errorMessage(cause, "File could not be loaded."));
    } finally { setBusy(false); }
  };

  const newFile = () => {
    if (busy || pending || closeTarget !== null) return;
    if (tabs.length >= maxEditorTabs) { setError("Close a file tab before opening another; the editor is limited to 12 tabs."); return; }
    const id = ++tabSequence.current;
    const tab: EditorTab = { id, controller: getConfig().url, path: `untitled-${id}.py`,
      content: "", loadedPath: "", loadedContent: "", sha256: "", preview: null, writeResult: null };
    rememberTab(tab); restoreTab(tab);
  };

  const selectFile = (path: string) => {
    if (path) void loadFile(path); else newFile();
  };

  const closeTab = (id: number, discard = false) => {
    if (busy || pending) return;
    const tab = id === activeTab ? currentTab() : tabs.find(item => item.id === id);
    if (!tab) return;
    if (!discard && tabIsDirty(tab)) { setCloseTarget(id); return; }
    const remaining = tabs.filter(item => item.id !== id);
    setTabs(remaining); setCloseTarget(null);
    if (id === activeTab) {
      const next = [...remaining].reverse().find(tab => tab.controller === getConfig().url);
      setActiveTab(next?.id ?? null);
      restoreTab(next || { id: 0, controller: getConfig().url, path: "", content: "",
        loadedPath: "", loadedContent: "", sha256: "", preview: null, writeResult: null });
    }
  };

  const tabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, id: number) => {
    const index = tabs.findIndex(tab => tab.id === id);
    const nextIndex = event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
      : event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (nextIndex < 0) return;
    event.preventDefault(); switchTab(tabs[nextIndex].id);
    if (!busy && !pending && closeTarget === null && tabs[nextIndex].controller === getConfig().url) {
      document.getElementById(`workbench-tab-${tabs[nextIndex].id}`)?.focus();
    }
  };

  const showPreview = async () => {
    if (!filePath.trim() || busy) return;
    const controller = getConfig().url;
    setBusy(true); setError("");
    try {
      if (controller !== loadedController) throw new Error("Controller changed; reload the original file.");
      assertConnection();
      const result = await previewWorkbenchWrite(filePath.trim(), content, loadedSha256);
      assertConnection();
      if (controller !== getConfig().url) throw new Error("Controller changed; discard this preview.");
      setPreview(result);
    }
    catch (cause) { setError(errorMessage(cause, "Diff preview could not be created.")); }
    finally { setBusy(false); }
  };

  const captureApproval = (cause: unknown, action: PendingAction) => {
    try { assertConnection(); } catch { return false; }
    if (cause instanceof ApiError && cause.code === "NOUS_APPROVAL_REQUIRED" && cause.details?.approval_request_id && action.controller === getConfig().url) {
      setPending({ ...action, approvalId: String(cause.details.approval_request_id) }); return true;
    }
    return false;
  };

  const save = async (reviewed?: Extract<PendingAction, { kind: "save" }>) => {
    if (busy || !filePath.trim()) return;
    const action = reviewed || { kind: "save" as const, path: filePath.trim(), content, sha256: loadedSha256, approvalId: "", controller: loadedController };
    if (action.controller !== getConfig().url) { setError("Controller changed; review the original file again."); return; }
    setBusy(true); setError("");
    try {
      assertConnection();
      const result = await writeWorkbenchFile(action.path, action.content, action.sha256);
      assertConnection();
      if (action.controller !== getConfig().url) throw new Error("Controller changed; inspect the original save outcome.");
      setPreview(result); setLoadedPath(action.path); setLoadedContent(action.content); setLoadedSha256(result.after_sha256); setPending(null); setReference(undefined);
      await refresh(); await showEvents(result.run_id);
      setWriteResult(result);
    } catch (cause) {
      if (!captureApproval(cause, action)) setError(`${errorMessage(cause, "Save could not be confirmed.")} Reload original state before repeating; no automatic retry.`);
    } finally { setBusy(false); }
  };

  const decide = async (decision: "approve" | "deny") => {
    if (!pending || busy) return;
    const action = pending; setBusy(true); setError("");
    try {
      if (action.controller !== getConfig().url) throw new Error("Controller changed; review original request again.");
      assertConnection();
      await approvalAction(action.approvalId, decision);
      assertConnection(); setPending(null);
      if (action.controller !== getConfig().url) throw new Error("Controller changed; original request was not resumed.");
      setBusy(false);
      if (decision === "approve") {
        if (action.kind === "save") await save(action); else await run(action);
      }
    } catch (cause) { setError(errorMessage(cause, "Decision could not be confirmed.")); }
    finally { setBusy(false); }
  };

  const search = async () => {
    if (searchQuery.trim().length < 2 || busy) return;
    setBusy(true); setError("");
    const controller = getConfig().url;
    try {
      assertConnection();
      const result = await searchWorkbench(searchQuery.trim());
      assertConnection();
      if (controller !== getConfig().url) throw new Error("Controller changed; discard original search results.");
      setSearchResults(result.matches);
    }
    catch (cause) { setError(errorMessage(cause, "Workspace search failed.")); }
    finally { setBusy(false); }
  };

  const run = async (reviewed?: Extract<PendingAction, { kind: "run" }>) => {
    if (!profile || busy || !availableProfiles.some(item => item.name === profile)) return;
    const action = reviewed || { kind: "run" as const, profile, target: profile === "cargo-test" ? "" : runTarget.trim(), approvalId: "", controller: loadedController };
    if (action.controller !== getConfig().url) { setError("Controller changed; review original execution again."); return; }
    setBusy(true); setError(""); setRunResult(null);
    try {
      assertConnection();
      const result = await runWorkbenchProfile(action.profile, action.target, 120);
      assertConnection();
      if (action.controller !== getConfig().url) throw new Error("Controller changed; inspect original execution.");
      setRunResult(result); setPending(null); await refresh(); await showEvents(result.run_id);
    } catch (cause) {
      if (!captureApproval(cause, action)) setError(`${errorMessage(cause, "Execution outcome is unavailable.")} Outcome may be UNKNOWN; inspect original events before another execution.`);
    } finally { setBusy(false); }
  };

  const selectProfile = (value: string) => {
    setProfile(value);
    if (value === "pytest") setRunTarget("tests");
    else if (value === "cargo-test") setRunTarget("");
    else if (filePath) setRunTarget(filePath);
  };

  const proposalDrafts = activeTab === null ? [] : [currentTab(), ...tabs.filter(tab => tab.id !== activeTab)]
    .filter(tab => tab.controller === getConfig().url && tabIsDirty(tab))
    .map(tab => ({ path: tab.path, content: tab.content, expected_sha256: tab.sha256,
      expected_exists: !!tab.loadedPath }));

  const refreshAppliedFiles = async (proposal: WorkspaceProposal) => {
    const controller = getConfig().url;
    setBusy(true);
    try {
      assertConnection();
      const files = await Promise.all(proposal.files.map(file => fetchWorkbenchFile(file.path)));
      assertConnection();
      if (controller !== getConfig().url) throw new Error("Controller changed; inspect the original file evidence.");
      if (files.some(file => proposal.files.find(item => item.path === file.path)?.after_sha256 !== file.sha256)) {
        throw new Error("Files changed after the verified proposal; reload and review current versions.");
      }
      const original = activeTab === null ? null : currentTab();
      const refreshed = tabs.map(tab => {
        const cached = tab.id === original?.id ? original : tab;
        const file = files.find(item => item.path === cached.path);
        if (!file || cached.controller !== controller || (tabIsDirty(cached) && cached.content !== file.content)) return cached;
        return { ...cached, content: file.content, loadedContent: file.content,
          loadedPath: file.path, sha256: file.sha256, preview: null, writeResult: null };
      });
      setTabs(refreshed);
      const active = refreshed.find(tab => tab.id === activeTab);
      if (active) restoreTab(active);
      await refresh(); await showEvents(proposal.proposal_id);
    } catch (cause) { setError(errorMessage(cause, "Applied files could not be reloaded. Original evidence remains inspectable.")); }
    finally { setBusy(false); }
  };

  return <div className="developer-panel" style={{ display: "grid", gap: space.md }}>
    <details style={panel}><summary style={{ padding: space.md, cursor: "pointer" }}>Panel settings / 面板设置</summary><div className="developer-settings">
      <label>Editor size <select aria-label="Editor font size" value={layout.fontSize} onChange={event => setLayout(value => ({ ...value, fontSize: Number(event.target.value) }))}>{[12, 14, 16, 18].map(size => <option key={size}>{size}</option>)}</select></label>
      <label><input type="checkbox" checked={layout.conversation} onChange={event => setLayout(value => ({ ...value, conversation: event.target.checked }))} /> Collaboration panel</label>
      <label><input type="checkbox" checked={layout.activity} onChange={event => setLayout(value => ({ ...value, activity: event.target.checked }))} /> Persisted activity</label>
      {onOpenEnvironments && <button onClick={() => { if (protectedDraft || pending) setError("Save or explicitly discard the original drafts before leaving this panel."); else onOpenEnvironments(); }} disabled={busy} style={btnSecondary}>Open environments</button>}
      <p>Layout settings grant no permissions. Files stay in the configured workspace; code and containers still require admission and qualified isolation.</p>
    </div></details>
    <section style={{ ...panel, padding: space.md, display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
      <div>
        <div style={{ color: colors.text, fontWeight: typo.semibold }}>Professional Workbench</div>
        <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: 3 }}>
          {listing?.workspace || "Loading workspace…"} · compare-and-swap writes · strict sandbox · canonical EventStream
        </div>
      </div>
      <div style={{ color: colors.textSecondary, fontSize: typo.sm }}>
        Capabilities {capabilities ? `${capabilities.summary.available}/${capabilities.summary.registered} usable` : "checking…"}
      </div>
    </section>

    {error && <section role="alert" style={{ ...panel, padding: space.md, color: colors.danger, background: colors.dangerSoft }}>{error}</section>}

    <section aria-label="Recorded model input" style={{ ...panel, padding: space.md }}>
      <label>Inspect recorded Run <select aria-label="Recorded input Run" style={{ ...input, maxWidth: "100%" }} value={contextView?.runId || ""} onChange={event => setContextView(event.target.value ? { runId: event.target.value, controller: runController } : null)}>
        <option value="">Select a persisted Run</option>
        {contextRuns.map(item => <option key={item.run_id} value={item.run_id}>{item.run_id} · {item.state}</option>)}
      </select></label>
      <p>Recent canonical Runtime Runs. Non-model or legacy Runs may have no input manifest; missing evidence remains UNKNOWN.</p>
      {contextView && <ContextInspector {...contextView} onClose={() => setContextView(null)} />}
    </section>

    <div className={`developer-columns ${embeddedConversation && layout.conversation ? "with-collaboration" : ""}`}>
      <aside style={{ ...panel, overflow: "hidden" }}>
        <div style={{ padding: space.md, borderBottom: `1px solid ${colors.borderLight}` }}>
          <div style={{ display: "flex", gap: space.xs }}>
            <input aria-label="Search workspace" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="Search files" style={{ ...input, minWidth: 0, flex: 1 }} />
            <button onClick={() => void search()} disabled={busy || searchQuery.trim().length < 2} style={btnSecondary}>Find</button>
          </div>
          <div style={{ display: "flex", gap: space.xs, marginTop: space.sm }}>
            <button onClick={() => selectFile("")} disabled={busy || !!pending} style={btnSecondary}>New file</button>
            <button onClick={() => void refresh().catch(cause => setError(errorMessage(cause, "Refresh failed.")))} disabled={busy} style={btnSecondary}>Refresh</button>
          </div>
        </div>
        <div style={{ maxHeight: 520, overflow: "auto" }}>
          {(searchResults.length ? searchResults : listing?.files || []).map((item: WorkbenchFileEntry | { path: string; line: number; text: string }, index) => (
            <button key={`${item.path}-${"line" in item ? item.line : index}`} onClick={() => selectFile(item.path)} disabled={busy || !!pending} style={{ width: "100%", border: "none", borderBottom: `1px solid ${colors.borderLight}`, padding: space.md, background: filePath === item.path ? colors.accentSoft : colors.surface, color: filePath === item.path ? colors.accent : colors.text, cursor: "pointer", textAlign: "left", fontFamily: typo.font }}>
              <div style={{ fontFamily: typo.mono, fontSize: typo.xs, overflowWrap: "anywhere" }}>{item.path}{"line" in item ? `:${item.line}` : ""}</div>
              {"text" in item && <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.text}</div>}
            </button>
          ))}
          {!listing?.files.length && <div style={{ padding: space.md, color: colors.textTertiary, fontSize: typo.sm }}>No editable files found.</div>}
        </div>
      </aside>

      <main style={{ display: "grid", gap: space.md, minWidth: 0 }}>
        <section style={{ ...panel, overflow: "hidden" }}>
          <div role="tablist" aria-label="Open workspace files" className="developer-file-tabs">
            {tabs.map(tab => <div key={tab.id} className="developer-file-tab">
              <button id={`workbench-tab-${tab.id}`} role="tab" aria-label={tab.id === activeTab ? filePath : tab.path}
                aria-controls="workbench-editor" aria-selected={tab.id === activeTab} tabIndex={tab.id === activeTab ? 0 : -1}
                disabled={busy || !!pending || closeTarget !== null} onClick={() => switchTab(tab.id)} onKeyDown={event => tabKeyDown(event, tab.id)}
                style={{ ...btnSecondary, background: tab.id === activeTab ? colors.accentSoft : colors.surface }}>
                {tab.id === activeTab ? filePath : tab.path}{(tab.id === activeTab ? dirty : tabIsDirty(tab)) ? " •" : ""}
              </button>
              <button aria-label={`Close ${tab.id === activeTab ? filePath : tab.path}`} disabled={busy || !!pending || closeTarget !== null}
                onClick={() => closeTab(tab.id)} style={btnSecondary}>×</button>
            </div>)}
          </div>
          <div role="tabpanel" id="workbench-editor" aria-labelledby={activeTab === null ? undefined : `workbench-tab-${activeTab}`}>
          <div style={{ padding: space.md, borderBottom: `1px solid ${colors.borderLight}`, display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" }}>
            <input disabled={busy || !!pending || activeTab === null} aria-label="Workspace file path" value={filePath} onChange={(event) => { setFilePath(event.target.value); setPreview(null); setReference(undefined); }} placeholder="Open or create a file" style={{ ...input, flex: 1, minWidth: 0, fontFamily: typo.mono }} />
            <button onClick={() => { setReference({ path: filePath, sha256: loadedSha256, controller: loadedController }); setLayout(value => ({ ...value, conversation: true })); }} disabled={busy || !!pending || dirty || !loadedSha256} style={btnSecondary}>Discuss saved file</button>
            <span style={{ color: dirty ? colors.warning : colors.textTertiary, fontSize: typo.xs }}>{dirty ? "Unsaved" : loadedSha256 ? "Saved" : "No file selected"}</span>
            <button onClick={() => void showPreview()} disabled={busy || !!pending || !filePath.trim()} style={btnSecondary}>Preview diff</button>
            <button onClick={() => void save()} disabled={busy || !!pending || !filePath.trim() || !dirty || !preview} style={{ ...btnPrimary, opacity: busy || !!pending || !dirty || !preview ? 0.55 : 1 }}>Save atomically</button>
          </div>
          <textarea disabled={busy || !!pending || activeTab === null} aria-label="Code editor" value={content} onChange={(event) => { setContent(event.target.value); setPreview(null); setReference(undefined); }} spellCheck={false} style={{ width: "100%", minHeight: 420, resize: "vertical", border: "none", outline: "none", padding: space.lg, boxSizing: "border-box", background: colors.surface, color: colors.text, fontFamily: typo.mono, fontSize: layout.fontSize, lineHeight: 1.55 }} />
          </div>
        </section>

        {preview && <section style={{ ...panel, padding: space.md }}>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>Proposed / saved change</div>
          <div style={{ color: colors.textTertiary, fontSize: typo.xs, margin: `${space.xs} 0 ${space.sm}` }}>{preview.before_sha256 || "new file"} → {preview.after_sha256}</div>
          <pre style={{ margin: 0, maxHeight: 280, overflow: "auto", padding: space.md, borderRadius: radius.md, background: colors.bg, color: colors.textSecondary, fontFamily: typo.mono, fontSize: typo.xs, whiteSpace: "pre-wrap" }}>{preview.diff || "No content change."}</pre>
          {writeResult && <p style={{ overflowWrap: "anywhere", fontSize: typo.xs }}>Saved {writeResult.path} · Write run {writeResult.run_id}{writeResult.backup_path && ` · Backup: ${writeResult.backup_path}`}. This file-write record is not a process receipt or effect verification.</p>}
        </section>}

        <section style={{ ...panel, padding: space.md }}><WorkspaceProposals drafts={proposalDrafts}
          disabled={operationBusy || !!pending} onBusyChange={setProposalBusy}
          focusProposalId={focusProposalId} onApplied={refreshAppliedFiles} /></section>

        <section style={{ ...panel, padding: space.md }}>
          <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.sm }}>Strict execution</div>
          <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
            <select disabled={busy || !!pending} aria-label="Execution profile" value={profile} onChange={(event) => selectProfile(event.target.value)} style={input}>
              {availableProfiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
            <input aria-label="Execution target" value={runTarget} onChange={(event) => setRunTarget(event.target.value)} disabled={busy || !!pending || profile === "cargo-test"} placeholder="workspace-relative target" style={{ ...input, flex: 1, minWidth: 0, fontFamily: typo.mono }} />
            <button onClick={() => void run()} disabled={busy || !!pending || protectedDraft || !availableProfiles.some(item => item.name === profile) || (profile !== "cargo-test" && !runTarget.trim())} style={btnPrimary}>Run in sandbox</button>
          </div>
          <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: space.sm }}>Installed profiles are not authorization or proof of isolation. Fixed profiles only, network disabled; missing strict sandbox fails closed. Save changes before running.</div>
          {runResult && <pre style={{ margin: `${space.md} 0 0`, maxHeight: 300, overflow: "auto", padding: space.md, borderRadius: radius.md, background: colors.bg, color: runResult.ok ? colors.text : colors.danger, fontFamily: typo.mono, fontSize: typo.xs, whiteSpace: "pre-wrap" }}>{`run ${runResult.run_id}\nexit ${runResult.exit_code}\n${runResult.stdout}${runResult.stderr ? `\n${runResult.stderr}` : ""}`}</pre>}
        </section>
      </main>
      {embeddedConversation && <aside hidden={!layout.conversation} className="developer-collaboration" aria-label="Workspace collaboration"><div className="developer-activity"><button style={btnSecondary} aria-pressed={collaborationMode === "ask"} disabled={busy} onClick={() => setCollaborationMode("ask")}>Ask / 只读分析</button><button style={btnSecondary} aria-pressed={collaborationMode === "edit"} disabled={busy} onClick={() => setCollaborationMode("edit")}>Edit / 审查提案</button></div><p>File references grant no authority. Edit prepares proposals for human review; execution and tests still require their own admission and backend.</p><ChatView conversationId={conversationId} onConversationCreated={setConversationId} workspaceFile={reference} onClearWorkspaceFile={() => setReference(undefined)} readOnly={collaborationMode === "ask"} onProposalCreated={setFocusProposalId} onCardClick={event => { const runId = String(event.payload?.run_id || event.metadata?.run_id || ""); if (runId) void showEvents(runId); }} onTraceClick={showTrace} /></aside>}
    </div>
    {closeTarget !== null && <section role="alert" style={{ ...panel, padding: space.md }}><p>Unsaved changes in {closeTarget === activeTab ? filePath : tabs.find(tab => tab.id === closeTarget)?.path}. Keep editing or explicitly discard this draft before closing.</p><button style={btnSecondary} onClick={() => setCloseTarget(null)}>Keep editing</button><button style={btnSecondary} onClick={() => closeTab(closeTarget, true)}>Discard draft and close</button></section>}
    {pending && <section aria-label="Workbench approval" style={{ ...panel, padding: space.md }}><h3>Explicit approval required</h3><p>Review the original {pending.kind} request: {pending.kind === "save" ? pending.path : `${pending.profile} ${pending.target}`}. Installation, model output and layout settings grant no authority.</p><p>Request {pending.approvalId}</p><button disabled={busy} style={btnPrimary} onClick={() => void decide("approve")}>Approve once and {pending.kind}</button><button disabled={busy} style={btnSecondary} onClick={() => void decide("deny")}>Deny original request</button></section>}
    {layout.activity && <section aria-label="Workspace persisted activity" style={{ ...panel, padding: space.md }}><h3>Workspace activity</h3><p>Actual EventStream file changes and executions, not keystrokes or monitoring of other applications. File content is not automatically sent to a model.</p><div className="developer-activity">{runs.length ? runs.map(item => <button key={item.run_id} onClick={() => void showEvents(item.run_id)} style={btnSecondary}>{item.task_id} · {item.state}</button>) : <p>No persisted workspace operations.</p>}</div>{selectedRun && <p>Run {selectedRun}</p>}{events.map((event, index) => <details key={event.event_id || index}><summary>{event.sequence} · {event.event_type} · {event.timestamp}</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(event.payload, null, 2)}</pre></details>)}</section>}
    {traceView && traceView.controller === getConfig().url && <DetailDrawer view={{ kind: "trace", traceId: traceView.traceId }} onClose={() => setTraceView(null)} />}
  </div>;
}
