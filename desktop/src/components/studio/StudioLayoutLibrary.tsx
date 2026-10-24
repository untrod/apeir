import { useEffect, useRef, useState } from "react";
import { api, captureRuntimeConnection, getConfig } from "../../lib/api";
import { changeStudioLibrary, layoutForScope, readStudioLibrary, STUDIO_LIBRARY_KEY, visibleLayouts, workspaceLayoutScope, type SavedLayout, type StudioLibrary } from "../../lib/studioLibrary";
import type { LayoutKind, StudioLayout } from "../../lib/studioLayout";

export function StudioLayoutLibrary({ current, load, exportLayout, close, locale }: { current: () => StudioLayout; load: (layout: StudioLayout) => void; exportLayout: (layout: StudioLayout) => void; close: () => void; locale: "en" | "zh" }) {
  const [initial] = useState(() => { try { return { library: readStudioLibrary(localStorage), error: "" }; } catch (error) { return { library: { schemaVersion: 1, revision: 0, entries: [] } as StudioLibrary, error: `Saved library rejected and preserved: ${String(error)}` }; } });
  const [library, setLibrary] = useState(initial.library), [message, setMessage] = useState(initial.error);
  const [name, setName] = useState(() => { try { return current().name; } catch { return "Layout"; } }), [kind, setKind] = useState<LayoutKind>("global");
  const [workspace, setWorkspace] = useState<string | null>(null), [selected, setSelected] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [guard] = useState(captureRuntimeConnection); const alive = useRef(false);
  const pending = useRef(new Set<AbortController>());
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const workspaceKey = async () => {
    guard();
    const abort = new AbortController(); pending.current.add(abort);
    let health: { workspace_available: boolean; workspace_path: string };
    try { health = await api<typeof health>("/api/v1/health/detailed", { signal: abort.signal }); }
    finally { pending.current.delete(abort); }
    guard();
    if (health.workspace_available !== true || typeof health.workspace_path !== "string") throw new Error("BLOCKED · Current Runtime has no verified workspace directory.");
    const key = await workspaceLayoutScope(getConfig().url, health.workspace_path); guard();
    if (alive.current) setWorkspace(key); return key;
  };
  const perform = async (action: () => Promise<void>) => {
    if (busy) return; setBusy(true);
    try { guard(); await action(); guard(); } catch (error) { if (alive.current) setMessage(String(error)); }
    finally { if (alive.current) setBusy(false); }
  };
  useEffect(() => {
    alive.current = true;
    const changed = (event: StorageEvent) => { if (event.key === STUDIO_LIBRARY_KEY) setMessage("Library changed in another window. Reload before editing."); };
    window.addEventListener("storage", changed); const requests = pending.current;
    return () => { alive.current = false; window.removeEventListener("storage", changed); requests.forEach(abort => abort.abort()); };
  }, []);
  const selectedEntry = visibleLayouts(library, workspace).find(entry => entry.id === selected);
  const mutate = async (edit: (entries: SavedLayout[]) => SavedLayout[]) => {
    guard(); const next = await changeStudioLibrary(localStorage, library.revision, entries => { guard(); if (!alive.current) throw new Error("Retired layout interaction."); return edit(entries); }); guard();
    if (alive.current) { setLibrary(next); setMessage("Presentation library saved. No Runtime task was executed."); }
  };
  const scope = async (entry?: SavedLayout) => {
    if ((entry?.scope.kind ?? kind) !== "workspace") return { kind: entry?.scope.kind ?? kind };
    const key = await workspaceKey();
    if (entry && entry.scope.workspace !== key) throw new Error("Workspace changed. Reload its library before loading this layout.");
    return { kind: "workspace" as const, workspace: key };
  };
  return <section role="dialog" aria-modal="false" aria-label="Saved layout library" className="studio-layout-library">
    <header><strong>{t("Layout library", "布局库")}</strong><button onClick={close}>{t("Close library", "关闭布局库")}</button></header>
    <details className="studio-card-details"><summary>{t("About saved layouts", "关于保存的布局")}</summary><p>{t("Workspace layouts belong to the current Runtime directory. Layouts contain presentation settings, never file drafts, credentials or permissions.", "工作区布局属于当前 Runtime 目录，仅保存展示设置，不包含文件草稿、凭据或权限。")}</p></details>
    <label>{t("Layout name", "布局名称")}<input autoFocus aria-label="Layout name" maxLength={64} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>{t("Save as", "保存类型")}<select aria-label="Layout scope" value={kind} disabled={busy} onChange={event => {
      const next = event.target.value as LayoutKind; setKind(next); setSelected(null);
      if (next === "workspace") void perform(async () => { await workspaceKey(); });
    }}><option value="global">Global / 全局</option><option value="workspace">Workspace / 工作区</option><option value="dashboard">Dashboard / 仪表盘</option><option value="template">Template / 模板</option></select></label>
    <button disabled={busy || !name.trim()} onClick={() => void perform(async () => {
      const document = layoutForScope(current(), kind, name); const namespace = await scope();
      const id = `layout-${crypto.randomUUID()}`;
      await mutate(entries => [...entries, { id, scope: namespace, document }]); if (alive.current) setSelected(id);
    })}>{t("Save current as new", "保存当前为新布局")}</button>
    <button disabled={busy} onClick={() => { try { guard(); setLibrary(readStudioLibrary(localStorage)); setSelected(null); setMessage(""); } catch (error) { setMessage(String(error)); } }}>{t("Reload library", "重新读取布局库")}</button>
    <ul>{visibleLayouts(library, workspace).map(entry => <li key={entry.id}><button disabled={busy} aria-pressed={selected === entry.id} onClick={() => { setSelected(entry.id); setName(entry.document.name); }}>{entry.document.name} · {entry.scope.kind}</button></li>)}</ul>
    {selectedEntry && <div className="studio-library-actions">
      <button disabled={busy} onClick={() => void perform(async () => { await scope(selectedEntry); guard(); load(selectedEntry.document); })}>{t("Load selected", "载入选中布局")}</button>
      <button disabled={busy} onClick={() => void perform(async () => {
        await scope(selectedEntry); const copy = { ...selectedEntry, id: `layout-${crypto.randomUUID()}`, document: { ...selectedEntry.document, name: `${selectedEntry.document.name.slice(0, 58)} copy` } };
        await mutate(entries => [...entries, copy]); if (alive.current) { setSelected(copy.id); setName(copy.document.name); }
      })}>{t("Duplicate selected", "复制选中布局")}</button>
      <button disabled={busy || !name.trim()} onClick={() => void perform(async () => { await scope(selectedEntry); await mutate(entries => entries.map(entry => entry.id === selected ? { ...entry, document: { ...entry.document, name } } : entry)); })}>{t("Rename selected", "重命名选中布局")}</button>
      <button disabled={busy} onClick={() => { guard(); exportLayout(selectedEntry.document); }}>{t("Export selected", "导出选中布局")}</button>
      <button disabled={busy} onClick={() => void perform(async () => { await scope(selectedEntry); await mutate(entries => entries.filter(entry => entry.id !== selected)); if (alive.current) setSelected(null); })}>{t("Remove selected", "删除选中布局")}</button>
    </div>}
    {kind === "workspace" && !workspace && <p role="status">PENDING · Resolve the current workspace before using workspace layouts.</p>}
    {message && <p role="status">{message}</p>}
  </section>;
}
