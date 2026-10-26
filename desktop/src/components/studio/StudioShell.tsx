import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Actions, DockLocation, I18nLabelDefaults, Layout, Model, TabNode, type Action } from "flexlayout-react";
import { useRuntimeConfigVersion } from "../../store";
import { getConfig, getRuntimeConfigVersion } from "../../lib/api";
import { useTheme } from "../../theme";
import { compactDashboard } from "../../lib/studioDashboard";
import { typo } from "../../design";
import { captureStudioLayout, createStudioLayout, discardsProtectedPanel, dockStudioTab, focusStudioTab, loadStudioLayout, MAX_LAYOUT_BYTES, parseStudioLayout, STUDIO_LAYOUT_KEY, STUDIO_TEMPLATES, studioModel, type StudioLayout } from "../../lib/studioLayout";
import { useStudioPanels, StudioPanel, StudioSnapshot } from "./StudioPanels";
import type { WorkbenchDraft } from "../DeveloperWorkbench";
import { StudioIcon } from "./StudioIcon";
import { StudioPresentation } from "./StudioPresentation";
import { StudioLayoutLibrary } from "./StudioLayoutLibrary";
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

export function StudioShell({ onProtectedChange, onExit }: { onProtectedChange?: (value: boolean) => void; onExit?: () => void }) {
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
  return <div className="studio-shell" style={{ fontFamily: typo.font }}>
    {changed && <div role="status" className="studio-notice">Controller connection changed. Previous requests, approvals and panels were retired. Any unsaved editor drafts remain in memory only.
      <button onClick={() => { const archived = [...drafts.current].filter(([key]) => !key.startsWith(`${version}:`)); download(JSON.stringify({ purpose: "Private editor drafts; not a layout, proposal or permission", drafts: archived.map(([, files]) => files) }, null, 2), "apeir-private-drafts.json"); }}>Export previous private drafts</button>
      <button onClick={() => { for (const key of drafts.current.keys()) if (!key.startsWith(`${version}:`)) drafts.current.delete(key); protect(activeProtected.current); setChanged(false); }}>Discard previous drafts</button>
      <button onClick={() => setChanged(false)}>Dismiss</button>
    </div>}
    <StudioSession onExit={onExit} key={version} epoch={version} remember={remember} onProtectionChange={protect} />
  </div>;
}

function StudioSession(props: React.ComponentProps<typeof StudioWorkspace>) {
  return <StudioSnapshot><StudioWorkspace {...props} /></StudioSnapshot>;
}

function StudioWorkspace({ epoch, remember, onProtectionChange, onExit }: { onExit?: () => void; epoch: number; remember: (key: string, value: WorkbenchDraft[]) => void; onProtectionChange: (value: boolean) => void }) {
  const { mode, setMode } = useTheme();
  const panels = useStudioPanels();
  const initial = useMemo(() => {
    try { return { layout: loadStudioLayout(localStorage), error: "" }; }
    catch (error) { return { layout: createStudioLayout(), error: `Saved layout was rejected and preserved: ${String(error)}` }; }
  }, []);
  const [document, setDocument] = useState<StudioLayout>(initial.layout);
  const [model, setModel] = useState(() => Model.fromJson(studioModel(initial.layout)));
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState(initial.error);
  const [editing, setEditing] = useState(false);
  const menu = useRef<HTMLDetailsElement>(null);
  const [query, setQuery] = useState("");
  const [picker, setPicker] = useState(false);
  const [library, setLibrary] = useState(false);
  const [windowMenu, setWindowMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const windowMenuElement = useRef<HTMLDivElement>(null);
  const windowMenuTrigger = useRef<HTMLButtonElement | null>(null);
  const preserveRejectedLayout = useRef(!!initial.error);
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
  const persistLayout = useCallback((announce: boolean) => {
    try {
      const saved = captureStudioLayout(model.toJson(), document);
      localStorage.setItem(STUDIO_LAYOUT_KEY, JSON.stringify(saved));
      preserveRejectedLayout.current = false;
      if (announce) setMessage(locale === "zh" ? "布局已保存。" : "Layout saved.");
    } catch (error) { setMessage(String(error)); }
  }, [document, model, locale]);
  const save = useCallback(() => persistLayout(true), [persistLayout]);
  useEffect(() => { if (windowMenu) windowMenuElement.current?.querySelector<HTMLButtonElement>("button")?.focus(); }, [windowMenu]);
  useEffect(() => {
    if (!revision || preserveRejectedLayout.current) return;
    const timer = window.setTimeout(() => persistLayout(false), 450);
    return () => window.clearTimeout(timer);
  }, [revision, persistLayout]);
  useEffect(() => {
    const flush = () => { if (revision && epoch === getRuntimeConfigVersion() && !preserveRejectedLayout.current) persistLayout(false); };
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, [epoch, revision, persistLayout]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) menu.current.open = false;
      if (event.target instanceof Node && !windowMenuElement.current?.contains(event.target) && !(event.target instanceof Element && event.target.closest(".studio-window-menu-button"))) setWindowMenu(null);
    };
    window.addEventListener("pointerdown", outside);
    return () => window.removeEventListener("pointerdown", outside);
  }, []);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.code === "KeyP") { event.preventDefault(); setPicker(value => !value); }
      if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === "KeyS") { event.preventDefault(); save(); }
      if (event.key === "Escape") { setPicker(false); setLibrary(false); if (windowMenuElement.current) windowMenuTrigger.current?.focus(); setWindowMenu(null); if (menu.current?.open) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); } }
      if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === "KeyL") { event.preventDefault(); setEditing(value => !value); }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [save]);
  useEffect(() => {
    const live = new Set(tabs.map(node => node.getId()));
    for (const [id, host] of hosts.current) if (!live.has(id)) { host.remove(); hosts.current.delete(id); }
  });
  const open = (type: string) => {
    if (!panels.some(panel => panel.type === type)) return;
    if (tabs.length >= 24) { setMessage("Panel limit reached (24)."); return; }
    let group = model.getActiveTabset();
    if (!group) model.visitNodes(node => { if (!group && node.getType() === "tabset") group = node as ReturnType<Model["getActiveTabset"]>; });
    const panel = panels.find(panel => panel.type === type)!;
    const maximized = model.getMaximizedTabset();
    if (maximized) model.doAction(Actions.maximizeToggle(maximized.getId()));
    const root = model.getRootRow();
    if (!group && !root) return;
    model.doAction(Actions.addTab({ type: "tab", id: `panel-${crypto.randomUUID()}`, component: type, name: panel[locale], ...(type === "dashboard" ? { config: compactDashboard() } : {}) }, group?.getId() ?? root!.getId(), group ? DockLocation.CENTER : DockLocation.RIGHT, -1, true));
    setRevision(value => value + 1); setPicker(false);
  };
  const reveal = (type: string) => {
    const existing = tabs.find(node => node.getComponent() === type);
    if (existing) { focusStudioTab(model, existing.getId()); setRevision(value => value + 1); }
    else open(type);
  };
  const replace = (next: StudioLayout) => {
    if (dirty.current.size) { setMessage("Save or resolve protected editor drafts and pending actions before replacing this layout."); return; }
    preserveRejectedLayout.current = false;
    setWindowMenu(null); setModel(Model.fromJson(studioModel(next))); setDocument(next); setRevision(value => value + 1); setMessage("Layout loaded. No Runtime action was executed.");
  };
  const action = (action: Action) => {
    if (discardsProtectedPanel(action, dirty.current)) {
      setMessage("Save or resolve this panel's draft or pending approval before closing it."); return undefined;
    }
    // Popouts may change the webview's trust boundary; keep them disabled.
    if ([Actions.POPOUT_TAB, Actions.POPOUT_TABSET, Actions.CREATE_SUBLAYOUT].includes(action.type)) return undefined;
    return action;
  };
  const maximized = model.getMaximizedTabset();
  const selectedType = model.getActiveTabset()?.getSelectedNode()?.getComponent();
  const quickPanels = [
    { type: "chat", icon: "chat", en: "Chat", zh: "对话" }, { type: "editor", icon: "files", en: "Files", zh: "文件" }, { type: "tasks", icon: "tasks", en: "Tasks", zh: "任务" },
    { type: "workflow", icon: "workflow", en: "Workflow", zh: "工作流" }, { type: "dashboard", icon: "dashboard", en: "Overview", zh: "概览" },
    { type: "models", icon: "model", en: "Models", zh: "模型" }, { type: "nodes", icon: "node", en: "Nodes", zh: "节点" }, { type: "evidence", icon: "evidence", en: "Evidence", zh: "证据" },
    { type: "operations", icon: "settings", en: "Console", zh: "控制台" },
  ] as const;
  const dockLabels: Record<string, string> = {
    "flexlayout.ui.close.tab": "关闭面板", "flexlayout.ui.close.tabset": "关闭面板组", "flexlayout.ui.active.tabset": "当前面板组",
    "flexlayout.ui.maximize.tabset": "最大化面板组", "flexlayout.ui.restore.tabset": "还原面板组", "flexlayout.ui.overflow.menu.tooltip": "隐藏的标签",
    "flexlayout.ui.splitter": "调整大小", "flexlayout.ui.move.tabset": "移动面板组", "flexlayout.ui.menu.maximize": "最大化", "flexlayout.ui.menu.restore": "还原",
  };
  return <StudioPresentation.Provider value={{ editing }}><section className={`studio-session ${editing ? "studio-editing" : "studio-browsing"}`} aria-label="APEIR Studio">
    <header className="studio-toolbar">
      <div className="studio-brand"><span className="studio-brand-mark" aria-hidden="true">A</span><strong>APEIR Studio</strong><span className="studio-workspace-name">{document.name}</span></div>
      <span className="studio-controller" title={getConfig().url}>{t("Runtime", "运行时")} · {getConfig().url.replace(/^https?:\/\//, "")}</span>
      <div className="studio-toolbar-actions">
      {maximized && <button onClick={() => { model.doAction(Actions.maximizeToggle(maximized.getId())); setRevision(value => value + 1); }}><StudioIcon name="restore" />{t("Show all panels", "还原所有面板")}</button>}
      <button onClick={() => setPicker(value => !value)} aria-expanded={picker} title={t("Add panel · Ctrl/⌘ Shift P", "添加面板 · Ctrl/⌘ Shift P")}><StudioIcon name="add" />{t("Add panel", "添加面板")}</button>
      <button className="studio-edit-toggle" aria-pressed={editing} onClick={() => setEditing(value => !value)} title={t("Ctrl/⌘ Alt L", "Ctrl/⌘ Alt L")}><StudioIcon name={editing ? "check" : "edit"} />{editing ? t("Done editing", "完成编辑") : t("Edit layout", "编辑布局")}</button>
      {editing && <button onClick={save}>{t("Save layout", "保存布局")}</button>}
      <details className="studio-menu" ref={menu}>
      <summary aria-label={t("Workspace menu", "工作区菜单")}>{t("Workspace", "工作区")} <span aria-hidden="true">⌄</span></summary>
      <div className="studio-menu-content">
      {onExit && <button onClick={onExit}>{t("Operations Console", "操作控制台")}</button>}
      <strong>{t("Layout", "布局")}</strong>
      {!editing && <button onClick={save}>{t("Save layout", "保存布局")}</button>}
      <button onClick={() => { setLibrary(value => !value); if (menu.current) menu.current.open = false; }} aria-expanded={library}>{t("Layout library", "布局库")}</button>
      <button onClick={() => { try { replace(loadStudioLayout(localStorage)); } catch (error) { setMessage(String(error)); } }}>{t("Load", "载入")}</button>
      <div className="studio-menu-row"><button onClick={() => { try { download(JSON.stringify(captureStudioLayout(model.toJson(), document), null, 2), "apeir-studio-layout.json"); } catch (error) { setMessage(String(error)); } }}>{t("Export", "导出")}</button><button onClick={() => input.current?.click()}>{t("Import", "导入")}</button></div>
      <label>{t("Template", "模板")} <select value={template} onChange={event => setTemplate(event.target.value)}>{Object.entries(STUDIO_TEMPLATES).map(([id, item]) => <option key={id} value={id}>{item[locale]}</option>)}</select></label>
      <button onClick={() => { replace(createStudioLayout(template, locale)); if (menu.current) menu.current.open = false; }}>{t("Apply preset", "应用预设")}</button>
      <button onClick={() => replace(createStudioLayout("general", locale))}>{t("Reset", "重置")}</button>
      <strong>{t("Appearance", "外观")}</strong>
      <label>{t("Language", "语言")}<select aria-label="Studio language" value={locale} onChange={event => setDocument(value => ({ ...value, locale: event.target.value as "en" | "zh" }))}><option value="en">English</option><option value="zh">中文</option></select></label>
      <label>{t("Theme", "主题")}<select aria-label="Studio theme" value={mode} onChange={event => setMode(event.target.value as "light" | "dark" | "system")}><option value="system">{t("System", "跟随系统")}</option><option value="dark">{t("Dark", "深色")}</option><option value="light">{t("Light", "浅色")}</option></select></label>
      <details className="studio-help"><summary>{t("Shortcuts & help", "快捷键与帮助")}</summary><p>{t("Drag a tab to an edge to split. Double-click its title bar to maximize or restore. Layout changes save automatically.", "拖动标签到边缘即可分屏；双击标题栏可最大化或还原。布局自动保存。")}</p><p>Ctrl/⌘ ⇧ P · {t("Panels", "面板")}<br/>Ctrl/⌘ Alt L · {t("Edit widgets", "编辑组件")}<br/>Ctrl/⌘ Alt S · {t("Save layout", "保存布局")}</p><p>{t("Layouts only change presentation. Closing a panel does not cancel its Work. Unsaved file drafts remain in memory until saved or explicitly exported.", "布局仅改变展示。关闭面板不会取消任务；未保存的文件草稿仅保留在内存中，请保存或明确导出。")}</p></details>
      </div></details></div>
      <input hidden ref={input} type="file" accept="application/json,.json" aria-label="Import Studio layout" onChange={async event => {
        const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
        try { if (file.size > MAX_LAYOUT_BYTES) throw new Error("Layout exceeds 96 KiB."); const text = await file.text(); replace(parseStudioLayout(text)); } catch (error) { setMessage(String(error)); }
      }} />
    </header>
    {picker && <section className="studio-picker" aria-label="Panel library"><label>{t("Search panels", "搜索面板")}<input autoFocus value={query} onChange={event => setQuery(event.target.value)} /></label>{panels.filter(panel => `${panel.en} ${panel.zh} ${panel.type}`.toLowerCase().includes(query.toLowerCase())).map(panel => <button title={panel.owner} key={panel.type} onClick={() => open(panel.type)}><strong>{panel[locale]}</strong></button>)}</section>}
    {library && <StudioLayoutLibrary locale={locale} current={() => captureStudioLayout(model.toJson(), document)} load={replace} exportLayout={layout => download(JSON.stringify(layout, null, 2), "apeir-studio-layout.json")} close={() => setLibrary(false)} />}
    {message && message !== t("Layout saved.", "布局已保存。") && <div role="status" className="studio-notice">{message}<button onClick={() => setMessage("")}>{t("Dismiss", "关闭提示")}</button></div>}
    <div className="studio-workbench">
      <nav className="studio-activity-rail" aria-label={t("Studio panels", "工作台面板")}>
        {quickPanels.map(item => { const panel = panels.find(panel => panel.type === item.type)!; return <button key={item.type} aria-label={`${t("Open", "打开")} ${panel[locale]}`} title={panel[locale]} aria-pressed={selectedType === item.type} onClick={() => reveal(item.type)}><StudioIcon name={item.icon} /><span>{item[locale]}</span></button>; })}
        <button aria-label={t("All panels", "所有面板")} title={t("All panels", "所有面板")} onClick={() => setPicker(value => !value)}><StudioIcon name="more" /><span>{t("More", "更多")}</span></button>
      </nav>
      <div className="studio-dock" data-layout-revision={revision}><Layout model={model} i18nTranslator={key => (locale === "zh" ? dockLabels[key] : undefined) ?? I18nLabelDefaults[key] ?? key} factory={node => <StudioPanelSlot host={getHost(node.getId())} />} onAction={action} onRenderTab={(node, values) => { const panel = panels.find(panel => panel.type === node.getComponent()); if (panel && [panel.type, panel.en, panel.zh].includes(node.getName())) values.content = panel[locale]; }} onRenderTabSet={(node, values) => {
        const selected = node.getSelectedNode();
        if (!selected) return;
        const panel = panels.find(panel => panel.type === selected.getComponent());
        values.buttons.unshift(<button key="arrange" className="studio-window-menu-button" aria-label={`${t("Arrange", "排列")} ${panel?.[locale] ?? selected.getName()}`} title={t("Snap, maximize or close", "贴靠、最大化或关闭")} onPointerDown={event => event.stopPropagation()} onClick={event => { windowMenuTrigger.current = event.currentTarget; const rect = event.currentTarget.getBoundingClientRect(); setWindowMenu({ id: selected.getId(), x: Math.max(8, Math.min(rect.right - 200, window.innerWidth - 208)), y: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 240)) }); }}><StudioIcon name="split" /></button>);
      }} onModelChange={() => setRevision(value => value + 1)} />
      {!tabs.length && <section className="studio-workspace-empty" aria-label={t("Empty workspace", "空白工作台")}><StudioIcon name="chat" /><h2>{t("Your workspace", "你的工作台")}</h2><p>{t("Open a panel to get started.", "打开面板，开始工作。")}</p><div><button onClick={() => reveal("chat")}>{t("Start a conversation", "开始对话")}</button><button onClick={() => reveal("editor")}>{t("Open project files", "打开项目文件")}</button><button onClick={() => setPicker(true)}>{t("Browse panels", "浏览所有面板")}</button></div></section>}
      </div>
    </div>
    {windowMenu && <div ref={windowMenuElement} role="menu" aria-label={t("Window arrangement", "窗口排列")} className="studio-window-menu" style={{ left: windowMenu.x, top: windowMenu.y }} onKeyDown={event => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
      const index = buttons.indexOf(window.document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }}>
      {([ ["left", "Snap left", "贴靠左侧"], ["right", "Snap right", "贴靠右侧"], ["top", "Snap top", "贴靠上方"], ["bottom", "Snap bottom", "贴靠下方"] ] as const).map(([side, en, zh]) => <button role="menuitem" key={side} onClick={() => { dockStudioTab(model, windowMenu.id, side); setRevision(value => value + 1); setWindowMenu(null); }}>{t(en, zh)}</button>)}
      <button role="menuitem" onClick={() => { const group = model.getNodeById(windowMenu.id)?.getParent(); if (group?.getType() === "tabset") { model.doAction(Actions.maximizeToggle(group.getId())); setRevision(value => value + 1); } setWindowMenu(null); }}>{maximized ? t("Restore panel", "还原面板") : t("Maximize panel", "最大化面板")}</button>
      <button role="menuitem" onClick={() => { const close = Actions.deleteTab(windowMenu.id); if (action(close)) { model.doAction(close); setRevision(value => value + 1); } setWindowMenu(null); }}>{t("Close panel", "关闭面板")}</button>
    </div>}
    {tabs.map(node => <StablePanel key={node.getId()} node={node} host={getHost(node.getId())} dirty={dirty.current} onProtectionChange={onProtectionChange} onSnapshot={value => remember(`${epoch}:${node.getId()}`, value)} open={open} inspect={setSelection} config={node.getConfig()} locale={locale} saveLayout={save} updateConfig={config => { if (JSON.stringify(node.getConfig()) !== JSON.stringify(config)) { model.doAction(Actions.updateNodeAttributes(node.getId(), { config })); setRevision(value => value + 1); } }} />)}
    <DetailDrawer view={selection} onClose={() => setSelection(null)} />
    <footer className="studio-footer"><span role="status">{message === t("Layout saved.", "布局已保存。") ? message : `${tabs.length} ${t(tabs.length === 1 ? "panel" : "panels", "个面板")}`}</span><span>{editing ? t("Editing layout", "正在编辑布局") : t("Workspace", "工作区")} · Ctrl/⌘ ⇧ P</span></footer>
  </section></StudioPresentation.Provider>;
}

function StablePanel({ node, host, dirty, onSnapshot, open, onProtectionChange, inspect, config, locale, updateConfig, saveLayout }: { config: unknown; locale: "en" | "zh"; updateConfig: (config: unknown) => void; saveLayout: () => void; node: TabNode; host: HTMLElement; dirty: Set<string>; onSnapshot: (drafts: WorkbenchDraft[]) => void; open: (type: string) => void; onProtectionChange: (value: boolean) => void; inspect: (view: DrawerView) => void }) {
  const callbacks = useRef({ onSnapshot, open }); callbacks.current = { onSnapshot, open };
  const id = node.getId();
  const onDraftChange = useCallback((value: boolean) => { if (value) dirty.add(id); else dirty.delete(id); onProtectionChange(dirty.size > 0); }, [dirty, id, onProtectionChange]);
  const onDraftSnapshot = useCallback((value: WorkbenchDraft[]) => callbacks.current.onSnapshot(value), []);
  const openPanel = useCallback((type: string) => callbacks.current.open(type), []);
  const isVisible = useCallback(() => host.isConnected && host.getClientRects().length > 0 && getComputedStyle(host).visibility !== "hidden", [host]);
  return createPortal(<StudioPanel config={config} locale={locale} updateConfig={updateConfig} saveLayout={saveLayout} isVisible={isVisible} type={node.getComponent() ?? "missing"} onDraftChange={onDraftChange} onDraftSnapshot={onDraftSnapshot} open={openPanel} inspect={inspect} />, host, id);
}
