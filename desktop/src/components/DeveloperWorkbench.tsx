import React, { useCallback, useEffect, useMemo, useState } from "react";

import { btnPrimary, btnSecondary, colors, radius, space, typo } from "../design";
import {
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
} from "../lib/api";
import { errorMessage } from "../lib/format";

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

export function DeveloperWorkbench() {
  const [listing, setListing] = useState<WorkbenchListing | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityAvailability | null>(null);
  const [filePath, setFilePath] = useState("");
  const [content, setContent] = useState("");
  const [loadedContent, setLoadedContent] = useState("");
  const [loadedSha256, setLoadedSha256] = useState("");
  const [preview, setPreview] = useState<WorkbenchPreview | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Array<{ path: string; line: number; text: string }>>([]);
  const [profile, setProfile] = useState("pytest");
  const [runTarget, setRunTarget] = useState("tests");
  const [runResult, setRunResult] = useState<WorkbenchRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    const [filesResult, capabilityResult] = await Promise.allSettled([
      fetchWorkbenchFiles(),
      fetchCapabilityAvailability(),
    ]);
    if (filesResult.status === "fulfilled") setListing(filesResult.value);
    if (capabilityResult.status === "fulfilled") setCapabilities(capabilityResult.value);
    const failure = [filesResult, capabilityResult].find((item) => item.status === "rejected");
    if (failure?.status === "rejected") setError(errorMessage(failure.reason, "Workbench data is unavailable."));
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const dirty = content !== loadedContent;
  const availableProfiles = useMemo(
    () => (listing?.profiles || []).filter((item) => item.available),
    [listing],
  );

  const loadFile = async (path: string) => {
    if (!path || busy) return;
    setBusy(true); setError(""); setPreview(null);
    try {
      const file = await fetchWorkbenchFile(path);
      setFilePath(file.path);
      setContent(file.content);
      setLoadedContent(file.content);
      setLoadedSha256(file.sha256);
      if (profile === "python" || profile === "python-compile" || profile === "node") setRunTarget(file.path);
    } catch (cause) {
      setError(errorMessage(cause, "File could not be loaded."));
    } finally { setBusy(false); }
  };

  const newFile = () => {
    setFilePath("untitled.py");
    setContent("");
    setLoadedContent("");
    setLoadedSha256("");
    setPreview(null);
  };

  const showPreview = async () => {
    if (!filePath.trim() || busy) return;
    setBusy(true); setError("");
    try { setPreview(await previewWorkbenchWrite(filePath.trim(), content, loadedSha256)); }
    catch (cause) { setError(errorMessage(cause, "Diff preview could not be created.")); }
    finally { setBusy(false); }
  };

  const save = async () => {
    if (!filePath.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const result = await writeWorkbenchFile(filePath.trim(), content, loadedSha256);
      setPreview(result);
      setLoadedContent(content);
      setLoadedSha256(result.after_sha256);
      await refresh();
      setRunResult({
        ok: true,
        run_id: result.run_id,
        profile: "workspace.write",
        target: result.path,
        exit_code: 0,
        stdout: `Saved ${result.path}${result.backup_path ? `\nBackup: ${result.backup_path}` : ""}`,
        stderr: "",
        runtime_seconds: 0,
        limit_exceeded: "",
        sandbox_id: "",
      });
    } catch (cause) { setError(errorMessage(cause, "File could not be saved.")); }
    finally { setBusy(false); }
  };

  const search = async () => {
    if (searchQuery.trim().length < 2 || busy) return;
    setBusy(true); setError("");
    try { setSearchResults((await searchWorkbench(searchQuery.trim())).matches); }
    catch (cause) { setError(errorMessage(cause, "Workspace search failed.")); }
    finally { setBusy(false); }
  };

  const run = async () => {
    if (!profile || busy) return;
    setBusy(true); setError(""); setRunResult(null);
    try {
      const target = profile === "cargo-test" ? "" : runTarget.trim();
      setRunResult(await runWorkbenchProfile(profile, target, 120));
      await refresh();
    } catch (cause) { setError(errorMessage(cause, "Governed execution failed.")); }
    finally { setBusy(false); }
  };

  const selectProfile = (value: string) => {
    setProfile(value);
    if (value === "pytest") setRunTarget("tests");
    else if (value === "cargo-test") setRunTarget("");
    else if (filePath) setRunTarget(filePath);
  };

  return <div style={{ display: "grid", gap: space.md }}>
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

    {error && <section style={{ ...panel, padding: space.md, color: colors.danger, background: colors.dangerSoft }}>{error}</section>}

    <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 280px) minmax(0, 1fr)", gap: space.md, alignItems: "start" }}>
      <aside style={{ ...panel, overflow: "hidden" }}>
        <div style={{ padding: space.md, borderBottom: `1px solid ${colors.borderLight}` }}>
          <div style={{ display: "flex", gap: space.xs }}>
            <input aria-label="Search workspace" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="Search files" style={{ ...input, minWidth: 0, flex: 1 }} />
            <button onClick={() => void search()} disabled={busy || searchQuery.trim().length < 2} style={btnSecondary}>Find</button>
          </div>
          <div style={{ display: "flex", gap: space.xs, marginTop: space.sm }}>
            <button onClick={newFile} style={btnSecondary}>New file</button>
            <button onClick={() => void refresh()} disabled={busy} style={btnSecondary}>Refresh</button>
          </div>
        </div>
        <div style={{ maxHeight: 520, overflow: "auto" }}>
          {(searchResults.length ? searchResults : listing?.files || []).map((item: WorkbenchFileEntry | { path: string; line: number; text: string }, index) => (
            <button key={`${item.path}-${"line" in item ? item.line : index}`} onClick={() => void loadFile(item.path)} style={{ width: "100%", border: "none", borderBottom: `1px solid ${colors.borderLight}`, padding: space.md, background: filePath === item.path ? colors.accentSoft : colors.surface, color: filePath === item.path ? colors.accent : colors.text, cursor: "pointer", textAlign: "left", fontFamily: typo.font }}>
              <div style={{ fontFamily: typo.mono, fontSize: typo.xs, overflowWrap: "anywhere" }}>{item.path}{"line" in item ? `:${item.line}` : ""}</div>
              {"text" in item && <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.text}</div>}
            </button>
          ))}
          {!listing?.files.length && <div style={{ padding: space.md, color: colors.textTertiary, fontSize: typo.sm }}>No editable files found.</div>}
        </div>
      </aside>

      <main style={{ display: "grid", gap: space.md, minWidth: 0 }}>
        <section style={{ ...panel, overflow: "hidden" }}>
          <div style={{ padding: space.md, borderBottom: `1px solid ${colors.borderLight}`, display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" }}>
            <input aria-label="Workspace file path" value={filePath} onChange={(event) => { setFilePath(event.target.value); setPreview(null); }} placeholder="relative/path.py" style={{ ...input, flex: 1, minWidth: 220, fontFamily: typo.mono }} />
            <span style={{ color: dirty ? colors.warning : colors.textTertiary, fontSize: typo.xs }}>{dirty ? "Unsaved" : "Saved"}</span>
            <button onClick={() => void showPreview()} disabled={busy || !filePath.trim()} style={btnSecondary}>Preview diff</button>
            <button onClick={() => void save()} disabled={busy || !filePath.trim() || !dirty} style={{ ...btnPrimary, opacity: busy || !dirty ? 0.55 : 1 }}>Save atomically</button>
          </div>
          <textarea aria-label="Code editor" value={content} onChange={(event) => { setContent(event.target.value); setPreview(null); }} spellCheck={false} style={{ width: "100%", minHeight: 420, resize: "vertical", border: "none", outline: "none", padding: space.lg, boxSizing: "border-box", background: colors.surface, color: colors.text, fontFamily: typo.mono, fontSize: typo.sm, lineHeight: 1.55 }} />
        </section>

        {preview && <section style={{ ...panel, padding: space.md }}>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>Verified change</div>
          <div style={{ color: colors.textTertiary, fontSize: typo.xs, margin: `${space.xs} 0 ${space.sm}` }}>{preview.before_sha256 || "new file"} → {preview.after_sha256}</div>
          <pre style={{ margin: 0, maxHeight: 280, overflow: "auto", padding: space.md, borderRadius: radius.md, background: colors.bg, color: colors.textSecondary, fontFamily: typo.mono, fontSize: typo.xs, whiteSpace: "pre-wrap" }}>{preview.diff || "No content change."}</pre>
        </section>}

        <section style={{ ...panel, padding: space.md }}>
          <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.sm }}>Strict execution</div>
          <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
            <select aria-label="Execution profile" value={profile} onChange={(event) => selectProfile(event.target.value)} style={input}>
              {availableProfiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
            <input aria-label="Execution target" value={runTarget} onChange={(event) => setRunTarget(event.target.value)} disabled={profile === "cargo-test"} placeholder="workspace-relative target" style={{ ...input, flex: 1, minWidth: 220, fontFamily: typo.mono }} />
            <button onClick={() => void run()} disabled={busy || !profile || (profile !== "cargo-test" && !runTarget.trim())} style={btnPrimary}>Run in sandbox</button>
          </div>
          <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: space.sm }}>No arbitrary shell: only installed, fixed development profiles are exposed. Network is disabled.</div>
          {runResult && <pre style={{ margin: `${space.md} 0 0`, maxHeight: 300, overflow: "auto", padding: space.md, borderRadius: radius.md, background: colors.bg, color: runResult.ok ? colors.text : colors.danger, fontFamily: typo.mono, fontSize: typo.xs, whiteSpace: "pre-wrap" }}>{`run ${runResult.run_id}\nexit ${runResult.exit_code}\n${runResult.stdout}${runResult.stderr ? `\n${runResult.stderr}` : ""}`}</pre>}
        </section>
      </main>
    </div>
  </div>;
}