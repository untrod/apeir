import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Actions, DockLocation, Layout, Model, TabNode, type Action } from "flexlayout-react";
import { useRuntimeConfigVersion } from "../../store";
import { getConfig } from "../../lib/api";
import { useTheme } from "../../theme";
import { captureStudioLayout, createStudioLayout, discardsProtectedPanel, loadStudioLayout, MAX_LAYOUT_BYTES, parseStudioLayout, STUDIO_LAYOUT_KEY, STUDIO_TEMPLATES, studioModel, type StudioLayout } from "../../lib/studioLayout";
import { STUDIO_PANELS, StudioPanel, StudioSnapshot } from "./StudioPanels";
import type { WorkbenchDraft } from "../DeveloperWorkbench";
import { DetailDrawer, type DrawerView } from "../DetailDrawer";
import "flexlayout-react/style/light.css";
import "./StudioShell.css";

/** Moving the DOM host preserves the mounted React tree and all unsaved editor state. */
export function StudioPanelSlot({ host }: { host: HTMLElement }) {
  const slot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const target = slot.current;
    target?.appendChild(host);
    return () => { if (host.parentNode === target) host.remove(); };
  }, [host]);
  return <div className="studio-slot" ref={slot} />;
}
function download(value: string, filename: string, mime = "application/json") {
  const url = URL.createObjectURL(new Blob([value], { type: mime }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function StudioShell({ onProtectedChange }: { onProtectedChange?: (value: boolean) => void }) {
  const version = useRuntimeConfigVersion();
  const drafts = useRef(new Map<string, WorkbenchDraft[]>());
  const previous = useRef(version);
  const [changed, setChanged] = useState(false);
  const activeProtected = useRef(false);
  useEffect(() => { if (previous.current !== version) { setChanged(true); previous.current = version; } }, [version]);
  const remember = useCallback((key: string, value: WorkbenchDraft[]) => {
    if (value.length) drafts.current.set(key, value); else drafts.current.delete(key);
  }, []);
  const protect = useCallback((value: boolean) => {
    activeProtected.current = value;
    onProtectedChange?.(value || [...drafts.current.keys()].some(key => !key.startsWith(`${version}:`)));
  }, [onProtectedChange, version]);
  useEffect(() => { protect(false); }, [protect]);
  return <div className="studio-shell">
    {changed && <div role="status" className="studio-notice">Controller connection changed. Previous requests, approvals and panels were retired. Any unsaved editor drafts remain in memory only.
      <button onClick={() => { const archived = [...drafts.current].filter(([key]) => !key.startsWith(`${version}:`)); download(JSON.stringify({ purpose: "Private editor drafts; not a layout, proposal or permission", drafts: archived.map(([, files]) => files) }, null, 2), "apeir-private-drafts.json"); }}>Export previous private drafts</button>
      <button onClick={() => { for (const key of drafts.current.keys()) if (!key.startsWith(`${version}:`)) drafts.current.delete(key); protect(activeProtected.current); setChanged(false); }}>Discard previous drafts</button>
      <button onClick={() => setChanged(false)}>Dismiss</button>
    </div>}
    <StudioSession key={version} epoch={version} remember={remember} onProtectionChange={protect} />
  </div>;
}

function StudioSession({ epoch, remember, onProtectionChange }: { epoch: number; remember: (key: string, value: WorkbenchDraft[]) => void; onProtectionChange: (value: boolean) => void }) {
  const { mode, setMode } = useTheme();
  const initial = useMemo(() => {
    try { return { layout: loadStudioLayout(localStorage), error: "" }; }
    catch (error) { return { layout: createStudioLayout(), error: `Saved layout was rejected and preserved: ${String(error)}` }; }
  }, []);
  const [document, setDocument] = useState<StudioLayout>(initial.layout);
  const [model, setModel] = useState(() => Model.fromJson(studioModel(initial.layout)));
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState(initial.error);
  const [query, setQuery] = useState("");
  const [picker, setPicker] = useState(false);
  const [selection, setSelection] = useState<DrawerView>(null);
  const [template, setTemplate] = useState("general");
  const dirty = useRef(new Set<string>());
  const hosts = useRef(new Map<string, HTMLElement>());
  const input = useRef<HTMLInputElement>(null);
  const locale = document.locale;
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const tabs: TabNode[] = [];
  model.visitNodes(node => { if (node instanceof TabNode) tabs.push(node); });
  const getHost = (id: string) => {
    let host = hosts.current.get(id);
    if (!host) { host = window.document.createElement("div"); host.className = "studio-panel-host"; hosts.current.set(id, host); }
    return host;
  };
  const save = useCallback(() => {
    try {
      const saved = captureStudioLayout(model.toJson(), document);
      localStorage.setItem(STUDIO_LAYOUT_KEY, JSON.stringify(saved));
      setDocument(saved); setMessage(locale === "zh" ? "布局已保存；不包含草稿、凭据或权限。" : "Layout saved; drafts, credentials and permissions are excluded.");
    } catch (error) { setMessage(String(error)); }
  }, [document, model, locale]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.code === "KeyP") { event.preventDefault(); setPicker(value => !value); }
      if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === "KeyS") { event.preventDefault(); save(); }
      if (event.key === "Escape") setPicker(false);
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [save]);
  useEffect(() => {
    const live = new Set(tabs.map(node => node.getId()));
    for (const [id, host] of hosts.current) if (!live.has(id)) { host.remove(); hosts.current.delete(id); }
  });
  const open = (type: string) => {
    if (!STUDIO_PANELS.some(panel => panel.type === type)) return;
    if (tabs.length >= 24) { setMessage("Panel limit reached (24)."); return; }
    let group = model.getActiveTabset();
    if (!group) model.visitNodes(node => { if (!group && node.getType() === "tabset") group = node as ReturnType<Model["getActiveTabset"]>; });
    if (!group) { setMessage("Reset to a workspace template before adding a panel."); return; }
    const panel = STUDIO_PANELS.find(panel => panel.type === type)!;
    model.doAction(Actions.addTab({ type: "tab", id: `panel-${crypto.randomUUID()}`, component: type, name: panel[locale] }, group.getId(), DockLocation.CENTER, -1));
    setRevision(value => value + 1); setPicker(false);
  };
  const replace = (next: StudioLayout) => {
    if (dirty.current.size) { setMessage("Save or resolve protected editor drafts and pending actions before replacing this layout."); return; }
    setModel(Model.fromJson(studioModel(next))); setDocument(next); setRevision(value => value + 1); setMessage("Layout loaded. No Runtime action was executed.");
  };
  const action = (action: Action) => {
    if (discardsProtectedPanel(action, dirty.current)) {
      setMessage("Save or resolve this panel's draft or pending approval before closing it."); return undefined;
    }
    // Popouts may change the webview's trust boundary; keep them disabled.
    if ([Actions.POPOUT_TAB, Actions.POPOUT_TABSET, Actions.CREATE_SUBLAYOUT].includes(action.type)) return undefined;
    return action;
  };
  return <StudioSnapshot><section className="studio-session" aria-label="APEIR Studio">
    <header className="studio-toolbar">
      <strong>APEIR Studio</strong><span className="studio-controller" title={getConfig().url}>Runtime · {getConfig().url}</span>
      <button onClick={() => setPicker(value => !value)} aria-expanded={picker}>{t("Add panel", "添加面板")} <kbd>⇧⌘P</kbd></button>
      <label>{t("Template", "模板")} <select value={template} onChange={event => setTemplate(event.target.value)}>{Object.entries(STUDIO_TEMPLATES).map(([id, item]) => <option key={id} value={id}>{item[locale]}</option>)}</select></label>
      <button onClick={() => replace(createStudioLayout(template, locale))}>{t("Apply preset", "应用预设")}</button>
      <button onClick={save}>{t("Save layout", "保存布局")}</button>
      <button onClick={() => { try { replace(loadStudioLayout(localStorage)); } catch (error) { setMessage(String(error)); } }}>{t("Load", "载入")}</button>
      <button onClick={() => replace(createStudioLayout("general", locale))}>{t("Reset", "重置")}</button>
      <button onClick={() => download(JSON.stringify(captureStudioLayout(model.toJson(), document), null, 2), "apeir-studio-layout.json")}>{t("Export", "导出")}</button>
      <button onClick={() => input.current?.click()}>{t("Import", "导入")}</button>
      <input hidden ref={input} type="file" accept="application/json,.json" aria-label="Import Studio layout" onChange={async event => {
        const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
        try { if (file.size > MAX_LAYOUT_BYTES) throw new Error("Layout exceeds 96 KiB."); const text = await file.text(); replace(parseStudioLayout(text)); } catch (error) { setMessage(String(error)); }
      }} />
      <select aria-label="Studio language" value={locale} onChange={event => setDocument(value => ({ ...value, locale: event.target.value as "en" | "zh" }))}><option value="en">English</option><option value="zh">中文</option></select>
      <select aria-label="Studio theme" value={mode} onChange={event => setMode(event.target.value as "light" | "dark" | "system")}><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select>
    </header>
    {picker && <section className="studio-picker" aria-label="Panel library"><label>{t("Search panels", "搜索面板")}<input autoFocus value={query} onChange={event => setQuery(event.target.value)} /></label>{STUDIO_PANELS.filter(panel => `${panel.en} ${panel.zh} ${panel.type}`.toLowerCase().includes(query.toLowerCase())).map(panel => <button key={panel.type} onClick={() => open(panel.type)}><strong>{panel[locale]}</strong><small>{panel.owner}</small></button>)}</section>}
    {message && <div role="status" className="studio-notice">{message}<button onClick={() => setMessage("")}>{t("Dismiss", "关闭提示")}</button></div>}
    <div className="studio-dock" data-layout-revision={revision}><Layout model={model} factory={node => <StudioPanelSlot host={getHost(node.getId())} />} onAction={action} onModelChange={() => setRevision(value => value + 1)} /></div>
    {tabs.map(node => <StablePanel key={node.getId()} node={node} host={getHost(node.getId())} dirty={dirty.current} onProtectionChange={onProtectionChange} onSnapshot={value => remember(`${epoch}:${node.getId()}`, value)} open={open} inspect={setSelection} />)}
    <DetailDrawer view={selection} onClose={() => setSelection(null)} />
    <footer className="studio-footer">{t("Layout is presentation, never permission. Closing a panel does not cancel Work.", "布局不授予权限；关闭面板不会取消后台任务。")}</footer>
  </section></StudioSnapshot>;
}

function StablePanel({ node, host, dirty, onSnapshot, open, onProtectionChange, inspect }: { node: TabNode; host: HTMLElement; dirty: Set<string>; onSnapshot: (drafts: WorkbenchDraft[]) => void; open: (type: string) => void; onProtectionChange: (value: boolean) => void; inspect: (view: DrawerView) => void }) {
  const callbacks = useRef({ onSnapshot, open }); callbacks.current = { onSnapshot, open };
  const id = node.getId();
  const onDraftChange = useCallback((value: boolean) => { if (value) dirty.add(id); else dirty.delete(id); onProtectionChange(dirty.size > 0); }, [dirty, id, onProtectionChange]);
  const onDraftSnapshot = useCallback((value: WorkbenchDraft[]) => callbacks.current.onSnapshot(value), []);
  const openPanel = useCallback((type: string) => callbacks.current.open(type), []);
  return createPortal(<StudioPanel type={node.getComponent() ?? "missing"} onDraftChange={onDraftChange} onDraftSnapshot={onDraftSnapshot} open={openPanel} inspect={inspect} />, host, id);
}
