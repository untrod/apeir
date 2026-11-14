import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Actions, DockLocation, I18nLabelDefaults, Layout, Model, TabNode, type Action } from "flexlayout-react";
import { useRuntimeConfigVersion } from "../../store";
import { getRuntimeConfigVersion, type GlobalSearchResult } from "../../lib/api";
import { useTheme } from "../../theme";
import { compactDashboard } from "../../lib/studioDashboard";
import { typo } from "../../design";
import { activeStudioTab, captureStudioLayout, createStudioLayout, discardsProtectedPanel, dockStudioTab, focusStudioTab, loadStudioLayout, MAX_LAYOUT_BYTES, parseStudioLayout, STUDIO_LAYOUT_KEY, STUDIO_TEMPLATES, studioModel, studioMinimumSize, studioPanelSize, type StudioLayout } from "../../lib/studioLayout";
import { useStudioPanels, StudioPanel, StudioSnapshot, PANEL_GROUPS } from "./StudioPanels";
import { CommandPalette } from "../CommandPalette";
import type { PanelNavigation } from "./StudioPanels";
import type { WorkbenchDraft } from "../DeveloperWorkbench";
import { StudioIcon } from "./StudioIcon";
import { StudioPresentation } from "./StudioPresentation";
import { useStudioSnapshot } from "./StudioData";
import { StudioLayoutLibrary } from "./StudioLayoutLibrary";
import { DetailDrawer, type DrawerView } from "../DetailDrawer";
import { SettingsPage } from "../SettingsPage";
import type { NativeCredentialNotice } from "../../lib/nativeRuntime";
import "flexlayout-react/style/light.css";
import "./StudioShell.css";

const SETTINGS_DRAFT = "$studio-settings";
type SettingsSection = "general" | "models" | "credentials" | "advanced";

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
  const { locale } = useTheme();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const version = useRuntimeConfigVersion();
  const [settingsSection, setSettingsSection] = useState<SettingsSection | null>(null);
  const [lastSettingsSection, setLastSettingsSection] = useState<SettingsSection>("general");
  const [lastModelSection, setLastModelSection] = useState<"models" | "credentials">("models");
  const navigateSettings = useCallback((section: SettingsSection | null) => {
    setSettingsSection(section); if (section) setLastSettingsSection(section);
    if (section === "models" || section === "credentials") setLastModelSection(section);
  }, []);
  const [credentialNotice, setCredentialNotice] = useState<NativeCredentialNotice | null>(null);
  const credentialStored = useCallback((notice: NativeCredentialNotice) => {
    if (notice.version !== getRuntimeConfigVersion()) return;
    setCredentialNotice(notice);
  }, []);
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
  const archivedDrafts = [...drafts.current].filter(([key]) => !key.startsWith(`${version}:`));
  const showConnectionNotice = changed && (credentialNotice?.version !== version || archivedDrafts.length > 0);
  return <div className="studio-shell" style={{ fontFamily: typo.font }}>
    {showConnectionNotice && <div role="status" className="studio-notice">{t("Controller connection changed. Previous requests and approvals were retired.", "连接已切换，原连接的请求与审批已退出当前视图。")}
      {archivedDrafts.length > 0 && <><button onClick={() => { const archived = archivedDrafts; download(JSON.stringify({ purpose: "Private editor drafts; not a layout, proposal or permission", drafts: archived.map(([, files]) => files) }, null, 2), "apeir-private-drafts.json"); }}>{t("Export previous private drafts", "导出原连接的草稿")}</button>
      <button onClick={() => { for (const key of drafts.current.keys()) if (!key.startsWith(`${version}:`)) drafts.current.delete(key); protect(activeProtected.current); setChanged(false); }}>{t("Discard previous drafts", "放弃原连接的草稿")}</button></>}
      <button onClick={() => setChanged(false)}>{t("Dismiss", "关闭提示")}</button>
    </div>}
    <StudioSession onExit={onExit} key={version} epoch={version} remember={remember} onProtectionChange={protect} settingsSection={settingsSection} onSettingsChange={navigateSettings} lastSettingsSection={lastSettingsSection} lastModelSection={lastModelSection} credentialNotice={credentialNotice?.version === version ? credentialNotice : null} onCredentialStored={credentialStored} />
  </div>;
}

function StudioSession(props: React.ComponentProps<typeof StudioWorkspace>) {
  return <StudioSnapshot><StudioWorkspace {...props} /></StudioSnapshot>;
}

function StudioWorkspace({ epoch, remember, onProtectionChange, onExit, settingsSection, onSettingsChange, lastSettingsSection, lastModelSection, credentialNotice, onCredentialStored }: { onExit?: () => void; epoch: number; remember: (key: string, value: WorkbenchDraft[]) => void; onProtectionChange: (value: boolean) => void; settingsSection: SettingsSection | null; lastSettingsSection: SettingsSection; lastModelSection: "models" | "credentials"; onSettingsChange: (section: SettingsSection | null) => void; credentialNotice: NativeCredentialNotice | null; onCredentialStored: (notice: NativeCredentialNotice) => void }) {
  const { locale } = useTheme();
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
  const settings = settingsSection !== null;
  const [settingsVisited, setSettingsVisited] = useState(settings);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [credentialBusy, setCredentialBusy] = useState(false);
  const settingsTrigger = useRef<HTMLElement | null>(null);
  const settingsView = useRef<HTMLDivElement>(null);
  const libraryView = useRef<HTMLDivElement>(null);
  const dock = useRef<HTMLDivElement>(null);
  const automaticFocus = useRef<string>();
  const [compact, setCompact] = useState<string>();
  const lastFocused = useRef(new Map<string, string>());
  const lastSection = useRef(new Map<string, string>());
  const menu = useRef<HTMLDetailsElement>(null);
  const [query, setQuery] = useState("");
  const [utility, setUtility] = useState<"panels" | "layouts" | "commands" | null>(null);
  const [libraryVisited, setLibraryVisited] = useState(false);
  const utilityTrigger = useRef<HTMLElement | null>(null);
  const picker = utility === "panels", library = utility === "layouts";
  const closeUtility = useCallback(() => { setUtility(null); window.requestAnimationFrame(() => { if (utilityTrigger.current?.isConnected) utilityTrigger.current.focus(); }); }, []);
  const showUtility = useCallback((next: typeof utility) => {
    if (credentialBusy) return;
    if (!next) { closeUtility(); return; }
    utilityTrigger.current = window.document.activeElement as HTMLElement | null;
    if (menu.current) menu.current.open = false;
    setWindowMenu(null); if (next !== "commands") onSettingsChange(null);
    if (next === "layouts") setLibraryVisited(true);
    setUtility(next);
  }, [closeUtility, onSettingsChange, credentialBusy]);
  const [windowMenu, setWindowMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const windowMenuElement = useRef<HTMLDivElement>(null);
  const windowMenuTrigger = useRef<HTMLButtonElement | null>(null);
  const preserveRejectedLayout = useRef(!!initial.error);
  const [navigation, setNavigation] = useState<Record<string, PanelNavigation>>({});
  const [selection, setSelection] = useState<DrawerView>(null);
  const [template, setTemplate] = useState("general");
  const dirty = useRef(new Set<string>());
  const hosts = useRef(new Map<string, HTMLElement>());
  const input = useRef<HTMLInputElement>(null);
  const rememberView = useCallback((node?: TabNode) => {
    const type = node?.getComponent();
    if (!type || !node) return;
    lastFocused.current.set(type, node.getId());
    if (type === "files") lastFocused.current.set("editor", node.getId());
    const group = PANEL_GROUPS.find(item => (item.types as readonly string[]).includes(type));
    if (group) lastSection.current.set(group.id, type);
  }, []);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const previousLocale = useRef(locale);
  useEffect(() => { if (previousLocale.current !== locale) { previousLocale.current = locale; setRevision(value => value + 1); } }, [locale]);
  const tabs: TabNode[] = [];
  model.visitNodes(node => { if (node instanceof TabNode) tabs.push(node); });
  const getHost = (id: string) => {
    let host = hosts.current.get(id);
    if (!host) { host = window.document.createElement("div"); host.className = "studio-panel-host"; hosts.current.set(id, host); }
    return host;
  };
  const capture = useCallback(() => captureStudioLayout(model.toJson(), { ...document, locale }, automaticFocus.current), [model, document, locale]);
  const persistLayout = useCallback((announce: boolean) => {
    try {
      const saved = capture();
      localStorage.setItem(STUDIO_LAYOUT_KEY, JSON.stringify(saved));
      preserveRejectedLayout.current = false;
      if (announce) setMessage(locale === "zh" ? "布局已保存。" : "Layout saved.");
    } catch (error) { setMessage(String(error)); }
  }, [capture, locale]);
  const save = useCallback(() => persistLayout(true), [persistLayout]);
  const openSettings = useCallback((section?: SettingsSection) => {
    if (credentialBusy) return;
    settingsTrigger.current = window.document.activeElement as HTMLElement | null;
    if (menu.current) menu.current.open = false;
    onSettingsChange(section ?? lastSettingsSection); setSettingsVisited(true); setUtility(null); setWindowMenu(null);
  }, [onSettingsChange, lastSettingsSection, credentialBusy]);
  const closeSettings = useCallback(() => {
    if (credentialBusy) return false;
    onSettingsChange(null); window.requestAnimationFrame(() => { if (settingsTrigger.current?.isConnected) settingsTrigger.current.focus(); else dock.current?.closest(".studio-session")?.querySelector<HTMLButtonElement>(".studio-settings-entry")?.focus(); }); return true;
  }, [onSettingsChange, credentialBusy]);
  const settingsDraft = useCallback((value: boolean) => {
    if (value) dirty.current.add(SETTINGS_DRAFT); else dirty.current.delete(SETTINGS_DRAFT);
    setSettingsDirty(value);
    onProtectionChange(dirty.current.size > 0);
  }, [onProtectionChange]);
  const otherDrafts = useCallback(() => [...dirty.current].some(id => id !== SETTINGS_DRAFT), []);
  useEffect(() => {
    if (!settings) return;
    const frame = window.requestAnimationFrame(() => settingsView.current?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [settings]);
  useEffect(() => {
    if (!library) return;
    const frame = window.requestAnimationFrame(() => libraryView.current?.querySelector<HTMLInputElement>("input")?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [library]);

  useEffect(() => {
    const target = dock.current;
    if (!target) return;
    const fit = () => {
      const rect = target.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const splitter = parseFloat(getComputedStyle(target).getPropertyValue("--flexlayout-splitter-size")) || 8;
      const minimum = studioMinimumSize(model.toJson().layout, splitter);
      const constrained = rect.width < minimum.width || rect.height < minimum.height;
      const maximized = model.getMaximizedTabset();
      if (constrained && (!maximized || automaticFocus.current)) {
        let group = model.getActiveTabset();
        if (!group) model.visitNodes(node => { if (!group && node.getType() === "tabset") group = node as ReturnType<Model["getActiveTabset"]>; });
        if (group && group.getId() !== maximized?.getId()) {
          if (maximized) model.doAction(Actions.maximizeToggle(maximized.getId()));
          model.doAction(Actions.setActiveTabset(group.getId()));
          model.doAction(Actions.maximizeToggle(group.getId()));
        }
        automaticFocus.current = group?.getId(); setCompact(group?.getId());
      } else if (!constrained && automaticFocus.current) {
        if (maximized?.getId() === automaticFocus.current) model.doAction(Actions.maximizeToggle(maximized.getId()));
        automaticFocus.current = undefined; setCompact(undefined);
      }
    };
    const observer = new ResizeObserver(fit); observer.observe(target); fit();
    return () => observer.disconnect();
  }, [model, revision]);
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
      if (event.defaultPrevented) return;
      if (credentialBusy) { if ((event.ctrlKey || event.metaKey) && ["KeyK", "Comma", "KeyP", "KeyS", "KeyL"].includes(event.code)) event.preventDefault(); return; }
      if ((event.ctrlKey || event.metaKey) && event.code === "KeyK") { event.preventDefault(); showUtility(utility === "commands" ? null : "commands"); return; }
      if (utility === "commands") return;
      if ((event.ctrlKey || event.metaKey) && event.code === "Comma") { event.preventDefault(); if (!settings) openSettings(); else closeSettings(); return; }
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.code === "KeyP") { event.preventDefault(); showUtility(picker ? null : "panels"); }
      if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === "KeyS") { event.preventDefault(); save(); }
      if (event.key === "Escape") {
        if (windowMenu) { setWindowMenu(null); windowMenuTrigger.current?.focus(); }
        else if (menu.current?.open) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); }
        else if (utility) closeUtility();
        else if (settings) closeSettings();
        else if (selection) setSelection(null);
      }
      if ((event.ctrlKey || event.metaKey) && event.altKey && event.code === "KeyL") { event.preventDefault(); if (activeStudioTab(model)?.getComponent() === "dashboard") setEditing(value => !value); }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [save, openSettings, closeSettings, showUtility, closeUtility, model, picker, utility, settings, windowMenu, selection, credentialBusy]);
  useEffect(() => {
    const live = new Set(tabs.map(node => node.getId()));
    for (const [id, host] of hosts.current) if (!live.has(id)) { host.remove(); hosts.current.delete(id); }
  });
  const open = (type: string) => {
    if (type === "credentials") { openSettings("credentials"); return; }
    if (!panels.some(panel => panel.type === type)) return;
    if (tabs.length >= 24) { setMessage("Panel limit reached (24)."); return; }
    let group = model.getActiveTabset();
    if (!group) model.visitNodes(node => { if (!group && node.getType() === "tabset") group = node as ReturnType<Model["getActiveTabset"]>; });
    const panel = panels.find(panel => panel.type === type)!;
    const maximized = model.getMaximizedTabset();
    if (maximized) model.doAction(Actions.maximizeToggle(maximized.getId()));
    const root = model.getRootRow();
    if (!group && !root) return;
    const added = model.doAction(Actions.addTab({ type: "tab", id: `panel-${crypto.randomUUID()}`, component: type, name: panel[locale], ...studioPanelSize(type), ...(type === "dashboard" ? { config: compactDashboard() } : {}) }, group?.getId() ?? root!.getId(), group ? DockLocation.CENTER : DockLocation.RIGHT, -1, true));
    if (added instanceof TabNode) rememberView(added);
    setRevision(value => value + 1); closeUtility();
  };
  const reveal = (type: string) => {
    if (credentialBusy) return;
    setUtility(null); setWindowMenu(null); onSettingsChange(null); if (menu.current) menu.current.open = false;
    if (type === "credentials") { openSettings("credentials"); return; }
    const compatible = type === "editor" ? ["editor", "files"] : [type];
    const active = activeStudioTab(model);
    const existing = compatible.includes(active?.getComponent() || "") ? active : tabs.find(node => node.getId() === lastFocused.current.get(type) && compatible.includes(node.getComponent() || "")) ?? tabs.find(node => compatible.includes(node.getComponent() || ""));
    if (existing) { focusStudioTab(model, existing.getId()); rememberView(existing); setRevision(value => value + 1); }
    else open(type);
    return existing ?? activeStudioTab(model);
  };
  const searchResult = (result: GlobalSearchResult) => {
    if (result.kind === "run") { setSelection({ kind: "run", runId: result.id }); return; }
    if (result.kind === "artifact") { setSelection({ kind: "artifact", artifactId: result.id }); return; }
    if (result.kind === "conversation" || result.kind === "file") {
      const type = result.kind === "conversation" ? "chat" : "editor";
      if (tabs.some(node => [type, ...(type === "editor" ? ["files"] : [])].includes(node.getComponent() || "") && dirty.current.has(node.getId()))) {
        setMessage(t("Finish the current draft before opening a search result in this panel.", "请先处理当前面板的草稿，再打开搜索结果。")); return;
      }
      const target = reveal(type);
      if (target) setNavigation(previous => ({ ...previous, [target.getId()]: { requestId: crypto.randomUUID(), ...(type === "chat" ? { conversationId: result.id } : { filePath: result.path || result.id }) } }));
    }
  };
  const commands = [
    ...panels.filter(panel => panel.type !== "credentials").map(panel => ({ id: panel.type, label: panel[locale], category: t("Open panel", "打开面板"), keywords: [panel.en, panel.zh, panel.type], action: () => reveal(panel.type) })),
    { id: "credentials", label: t("API keys", "API 密钥"), category: t("Settings", "设置"), keywords: ["credentials", "凭据"], action: () => openSettings("credentials") },
    { id: "settings", label: t("Settings", "设置"), keywords: ["preferences", "language", "语言", "theme", "主题"], category: t("Application", "应用"), action: () => openSettings() },
    { id: "layouts", label: t("Layout library", "布局库"), category: t("Workspace", "工作区"), action: () => showUtility("layouts") },
  ];
  const replace = (next: StudioLayout) => {
    if (dirty.current.size) { setMessage("Save or resolve protected editor drafts and pending actions before replacing this layout."); return; }
    preserveRejectedLayout.current = false;
    automaticFocus.current = undefined; setCompact(undefined); lastFocused.current.clear(); lastSection.current.clear();
    setNavigation({}); setSelection(null);
    setWindowMenu(null); setModel(Model.fromJson(studioModel(next))); setDocument(next); setRevision(value => value + 1); setMessage(t("Layout loaded.", "布局已载入。"));
  };
  const action = (action: Action) => {
    if (action.type === Actions.MAXIMIZE_TOGGLE && automaticFocus.current) {
      setMessage(t("Widen the window to restore the saved splits.", "增大窗口即可还原原有分屏。")); return undefined;
    }
    if (discardsProtectedPanel(action, dirty.current)) {
      setMessage("Save or resolve this panel's draft or pending approval before closing it."); return undefined;
    }
    // Popouts may change the webview's trust boundary; keep them disabled.
    if ([Actions.POPOUT_TAB, Actions.POPOUT_TABSET, Actions.CREATE_SUBLAYOUT].includes(action.type)) return undefined;
    return action;
  };
  const maximized = model.getMaximizedTabset();
  const selectedTab = activeStudioTab(model);
  const selectedType = selectedTab?.getComponent();
  const settingsQuery = !!query && /settings|设置|credentials?|api keys|密钥|凭据|language|语言|theme|主题/i.test(query);
  const section = PANEL_GROUPS.find(group => (group.types as readonly string[]).includes(selectedType || "")) ?? (selectedType?.startsWith("ui:") ? PANEL_GROUPS[PANEL_GROUPS.length - 1] : PANEL_GROUPS[1]);
  const dockLabels: Record<string, string> = {
    "flexlayout.ui.close.tab": "关闭面板", "flexlayout.ui.close.tabset": "关闭面板组", "flexlayout.ui.active.tabset": "当前面板组",
    "flexlayout.ui.maximize.tabset": "最大化面板组", "flexlayout.ui.restore.tabset": "还原面板组", "flexlayout.ui.overflow.menu.tooltip": "隐藏的标签",
    "flexlayout.ui.splitter": "调整大小", "flexlayout.ui.move.tabset": "移动面板组", "flexlayout.ui.menu.maximize": "最大化", "flexlayout.ui.menu.restore": "还原",
  };
  return <StudioPresentation.Provider value={{ editing }}><section className={`studio-session ${editing ? "studio-editing" : "studio-browsing"} ${compact ? "studio-compact" : ""}`} aria-label="APEIR Studio">
    <header className="studio-toolbar">
      <div className="studio-brand"><span className="studio-brand-mark" aria-hidden="true">A</span><strong>APEIR Studio</strong><span className="studio-workspace-name">{document.name}</span></div>
      {compact && <span className="studio-compact-label" title={t("Panels stay open. Widen the window to restore your splits.", "面板继续保留；增大窗口可还原分屏。")}>{t("Compact view", "紧凑视图")}</span>}
      <div className="studio-toolbar-actions">
      {maximized && !compact && <button onClick={() => { model.doAction(Actions.maximizeToggle(maximized.getId())); setRevision(value => value + 1); }}><StudioIcon name="restore" />{t("Show all panels", "还原所有面板")}</button>}
      <button disabled={credentialBusy} aria-label={t("Search APEIR", "搜索 APEIR")} title={t("Search · Ctrl/⌘ K", "搜索 · Ctrl/⌘ K")} onClick={() => showUtility("commands")}><StudioIcon name="search" /><span className="studio-search-label">{t("Search", "搜索")}</span><kbd>Ctrl K</kbd></button>
      <button disabled={credentialBusy} onClick={() => showUtility(picker ? null : "panels")} aria-expanded={picker} title={t("Add panel · Ctrl/⌘ Shift P", "添加面板 · Ctrl/⌘ Shift P")}><StudioIcon name="add" />{t("Add panel", "添加面板")}</button>
      {(selectedType === "dashboard" || editing) && <button className="studio-edit-toggle" aria-pressed={editing} onClick={() => setEditing(value => !value)} title={t("Ctrl/⌘ Alt L", "Ctrl/⌘ Alt L")}><StudioIcon name={editing ? "check" : "edit"} />{editing ? t("Done editing", "完成编辑") : t("Customize Overview", "自定义概览")}</button>}
      {editing && <button onClick={save}>{t("Save layout", "保存布局")}</button>}
      <details className="studio-menu" ref={menu} onToggle={event => { if (event.currentTarget.open) { setUtility(null); setWindowMenu(null); } }}>
      <summary aria-disabled={credentialBusy} onClick={event => { if (credentialBusy) event.preventDefault(); }} aria-label={t("Workspace menu", "工作区菜单")}>{t("Workspace", "工作区")} <span aria-hidden="true">⌄</span></summary>
      <div className="studio-menu-content">
      <button onClick={() => { if (menu.current) menu.current.open = false; openSettings(); }}>{t("Settings", "设置")} <kbd>Ctrl/⌘ ,</kbd></button>
      {onExit && <button onClick={onExit}>{t("Operations Console", "操作控制台")}</button>}
      <strong>{t("Layout", "布局")}</strong>
      {!editing && <button onClick={save}>{t("Save layout", "保存布局")}</button>}
      <button onClick={() => showUtility(library ? null : "layouts")} aria-expanded={library}>{t("Layout library", "布局库")}</button>
      <button onClick={() => { try { replace(loadStudioLayout(localStorage)); } catch (error) { setMessage(String(error)); } }}>{t("Load", "载入")}</button>
      <div className="studio-menu-row"><button onClick={() => { try { download(JSON.stringify(capture(), null, 2), "apeir-studio-layout.json"); } catch (error) { setMessage(String(error)); } }}>{t("Export", "导出")}</button><button onClick={() => input.current?.click()}>{t("Import", "导入")}</button></div>
      <label>{t("Template", "模板")} <select value={template} onChange={event => setTemplate(event.target.value)}>{Object.entries(STUDIO_TEMPLATES).map(([id, item]) => <option key={id} value={id}>{item[locale]}</option>)}</select></label>
      <button onClick={() => { replace(createStudioLayout(template, locale)); if (menu.current) menu.current.open = false; }}>{t("Apply preset", "应用预设")}</button>
      <button onClick={() => replace(createStudioLayout("general", locale))}>{t("Reset", "重置")}</button>
      <details className="studio-help"><summary>{t("Shortcuts & help", "快捷键与帮助")}</summary><p>{t("Drag a tab to an edge to split. Double-click its title bar to maximize or restore. Layout changes save automatically.", "拖动标签到边缘即可分屏；双击标题栏可最大化或还原。布局自动保存。")}</p><p>Ctrl/⌘ ⇧ P · {t("Panels", "面板")}<br/>Ctrl/⌘ Alt L · {t("Edit widgets", "编辑组件")}<br/>Ctrl/⌘ Alt S · {t("Save layout", "保存布局")}</p><p>{t("Layouts only change presentation. Closing a panel does not cancel its Work. Unsaved file drafts remain in memory until saved or explicitly exported.", "布局仅改变展示。关闭面板不会取消任务；未保存的文件草稿仅保留在内存中，请保存或明确导出。")}</p></details>
      </div></details></div>
      <input hidden ref={input} type="file" accept="application/json,.json" aria-label="Import Studio layout" onChange={async event => {
        const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
        try { if (file.size > MAX_LAYOUT_BYTES) throw new Error("Layout exceeds 96 KiB."); const text = await file.text(); replace(parseStudioLayout(text)); } catch (error) { setMessage(String(error)); }
      }} />
    </header>
    {picker && <section className="studio-picker" aria-label="Panel library">
      <header><label>{t("Search panels", "搜索面板")}<input autoFocus value={query} onChange={event => setQuery(event.target.value)} /></label><button aria-label={t("Close panel library", "关闭面板库")} onClick={closeUtility}>×</button></header>
      {[...PANEL_GROUPS, { id: "external", en: "Installed extensions", zh: "已安装扩展", types: panels.filter(panel => panel.type.startsWith("ui:")).map(panel => panel.type) }].map(group => {
        const matches = panels.filter(panel => (group.types as readonly string[]).includes(panel.type) && `${panel.en} ${panel.zh} ${panel.type}`.toLowerCase().includes(query.toLowerCase()));
        return matches.length > 0 && <details key={`${group.id}:${!!query}`} open={!!query || group.id === "develop"}><summary>{group[locale]} <small>{matches.length}</small></summary><div>{matches.map(panel => <button title={panel.owner} key={panel.type} onClick={() => open(panel.type)}>{panel[locale]}</button>)}</div></details>;
      })}
      {settingsQuery && <button onClick={() => openSettings(/credentials?|api keys|密钥|凭据/i.test(query) ? "credentials" : "general")}>{t("Settings", "设置")}</button>}
      {!settingsQuery && !panels.some(panel => panel.type !== "credentials" && `${panel.en} ${panel.zh} ${panel.type}`.toLowerCase().includes(query.toLowerCase())) && <p role="status">{t("No matching panels", "没有匹配的面板")}</p>}
    </section>}
    {(library || libraryVisited) && <div ref={libraryView} hidden={!library} className="studio-layout-library-view"><StudioLayoutLibrary locale={locale} current={capture} load={replace} exportLayout={layout => download(JSON.stringify(layout, null, 2), "apeir-studio-layout.json")} close={closeUtility} /></div>}
    {message && message !== t("Layout saved.", "布局已保存。") && <div role="status" className="studio-notice">{message}<button onClick={() => setMessage("")}>{t("Dismiss", "关闭提示")}</button></div>}
    <div className="studio-workbench">
      <nav className="studio-activity-rail" aria-label={t("Studio panels", "工作台面板")}>
        {PANEL_GROUPS.map(group => { const remembered = lastSection.current.get(group.id); return <button disabled={credentialBusy} key={group.id} aria-label={group[locale]} title={group[locale]} aria-pressed={section.id === group.id} onClick={() => reveal(remembered && tabs.some(node => node.getComponent() === remembered) ? remembered : group.primary)}><StudioIcon name={group.icon} /><span>{group[locale]}</span></button>; })}
        <button disabled={credentialBusy} aria-label={t("All panels", "所有面板")} title={t("All panels", "所有面板")} onClick={() => showUtility(picker ? null : "panels")}><StudioIcon name="more" /><span>{t("More", "更多")}</span></button>
        <button disabled={credentialBusy} className="studio-settings-entry" aria-label={t("Settings", "设置")} aria-description={settingsDirty ? t("Unsaved settings are retained", "未保存的设置仍保留") : undefined} title={t("Settings · Ctrl/⌘ ,", "设置 · Ctrl/⌘ ,")} onClick={() => openSettings()}><StudioIcon name="settings" /><span>{t("Settings", "设置")}{settingsDirty ? " •" : ""}</span></button>
      </nav>
      <div className="studio-content"><div className="studio-work-area" hidden={settings}><nav className="studio-section-tabs" aria-label={t("Section views", "分类视图")}><strong>{section[locale]}</strong>{section.types.filter(type => type !== "files" && !["diagnostics", "inspector", "operations"].includes(type)).map(type => { const panel = panels.find(panel => panel.type === type)!; return <button key={type} aria-label={`${t("Open", "打开")} ${panel[locale]}`} aria-pressed={selectedType === type || type === "editor" && selectedType === "files"} onClick={() => reveal(type)}>{type === "editor" ? t("Editor", "编辑") : type === "terminal" ? t("Commands", "命令") : panel[locale]}</button>; })}</nav>
      <div ref={dock} className="studio-dock" data-layout-revision={revision}><Layout model={model} i18nTranslator={key => (locale === "zh" ? dockLabels[key] : undefined) ?? I18nLabelDefaults[key] ?? key} factory={node => <StudioPanelSlot host={getHost(node.getId())} />} onAction={action} onRenderTab={(node, values) => { const panel = panels.find(panel => panel.type === node.getComponent()); if (panel && [panel.type, panel.en, panel.zh].includes(node.getName())) values.content = panel[locale]; }} onRenderTabSet={(node, values) => {
        const selected = node.getSelectedNode();
        if (!selected) return;
        const panel = panels.find(panel => panel.type === selected.getComponent());
        values.buttons.unshift(<button key="arrange" className="studio-window-menu-button" aria-label={`${t("Arrange", "排列")} ${panel?.[locale] ?? selected.getName()}`} title={t("Snap, maximize or close", "贴靠、最大化或关闭")} onPointerDown={event => event.stopPropagation()} onClick={event => { setUtility(null); if (menu.current) menu.current.open = false; windowMenuTrigger.current = event.currentTarget; const rect = event.currentTarget.getBoundingClientRect(); setWindowMenu(previous => previous?.id === selected.getId() ? null : { id: selected.getId(), x: Math.max(8, Math.min(rect.right - 200, window.innerWidth - 208)), y: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 240)) }); }}><StudioIcon name="split" /></button>);
      }} onModelChange={() => { rememberView(activeStudioTab(model)); setRevision(value => value + 1); }} />
      {!tabs.length && <section className="studio-workspace-empty" aria-label={t("Empty workspace", "空白工作台")}><StudioIcon name="chat" /><h2>{t("Your workspace", "你的工作台")}</h2><p>{t("Open a panel to get started.", "打开面板，开始工作。")}</p><div><button onClick={() => reveal("chat")}>{t("Start a conversation", "开始对话")}</button><button onClick={() => reveal("editor")}>{t("Open project files", "打开项目文件")}</button><button onClick={() => showUtility("panels")}>{t("Browse panels", "浏览所有面板")}</button></div></section>}
      </div>
      </div>
      {(settings || settingsVisited) && <div ref={settingsView} className="studio-settings-view" hidden={!settings}><SettingsPage initialSection={lastSettingsSection === "credentials" ? "models" : lastSettingsSection} initialModelSection={lastModelSection} onSectionChange={(section, modelSection) => onSettingsChange(section === "models" ? modelSection : section)} preferredCredential={credentialNotice} onCredentialStored={onCredentialStored} onCredentialBusyChange={setCredentialBusy} onClose={closeSettings} onOpenModels={() => reveal("models")} onOpenApprovals={() => reveal("operations")} onOpenLayouts={() => showUtility("layouts")} onDraftChange={settingsDraft} hasOtherDrafts={otherDrafts} hasProtectedChanges={() => dirty.current.size > 0} /></div>}
      <div className="studio-inspector-view" hidden={settings || !selection}><DetailDrawer presentation="docked" view={selection} onClose={() => setSelection(null)} /></div>
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
      <button role="menuitem" disabled={!!compact} onClick={() => { const group = model.getNodeById(windowMenu.id)?.getParent(); if (group?.getType() === "tabset") { model.doAction(Actions.maximizeToggle(group.getId())); setRevision(value => value + 1); } setWindowMenu(null); }}>{compact ? t("Compact view", "紧凑视图") : maximized ? t("Restore group", "还原面板组") : t("Maximize group", "最大化面板组")}</button>
      <button role="menuitem" onClick={() => { const close = Actions.deleteTab(windowMenu.id); if (action(close)) { model.doAction(close); setRevision(value => value + 1); } setWindowMenu(null); }}>{t("Close panel", "关闭面板")}</button>
    </div>}
    {tabs.map(node => <StablePanel key={node.getId()} node={node} host={getHost(node.getId())} navigation={navigation[node.getId()]} dirty={dirty.current} onProtectionChange={onProtectionChange} onSnapshot={value => remember(`${epoch}:${node.getId()}`, value)} open={reveal} inspect={setSelection} config={node.getConfig()} locale={locale} saveLayout={save} updateConfig={config => { if (JSON.stringify(node.getConfig()) !== JSON.stringify(config)) { model.doAction(Actions.updateNodeAttributes(node.getId(), { config })); setRevision(value => value + 1); } }} />)}
    <CommandPalette commands={commands} open={utility === "commands"} onClose={closeUtility} onSearchResult={searchResult} />
    <footer className="studio-footer"><span role="status">{message === t("Layout saved.", "布局已保存。") ? message : `${tabs.length} ${t(tabs.length === 1 ? "panel" : "panels", "个面板")}`}</span><StudioConnectionStatus disabled={credentialBusy} locale={locale} open={() => reveal("dashboard")} /><span>{editing ? t("Editing layout", "正在编辑布局") : t("Workspace", "工作区")} · Ctrl/⌘ ⇧ P</span></footer>
  </section></StudioPresentation.Provider>;
}

/** Reuse the shared health subscription; never add a status-bar poller. */
function StudioConnectionStatus({ locale, open, disabled }: { disabled: boolean; locale: "en" | "zh"; open: () => void }) {
  const { health, subscribeLive } = useStudioSnapshot();
  useEffect(() => subscribeLive(() => true, ["health"]), [subscribeLive]);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const runtime = health.error ? t("Unavailable", "不可用") : health.data?.running === true ? t("Online", "在线") : health.data?.running === false ? t("Offline", "离线") : "UNKNOWN";
  const kernel = health.error || !health.data?.kernel ? "UNKNOWN" : health.data.kernel.ready === true ? t("Ready", "就绪") : health.data.kernel.configured === false ? t("Not configured", "未配置") : health.data.kernel.ready === false ? t("Not ready", "未就绪") : "UNKNOWN";
  return <button disabled={disabled} className="studio-connection-status" aria-label={t("Open connection status", "查看连接状态")} onClick={open} title={health.receivedAt ? `${t("Last received", "最近更新")}: ${new Date(health.receivedAt).toLocaleTimeString()}` : "UNKNOWN"}>Runtime {runtime} · Kernel {kernel}</button>;
}

function StablePanel({ node, host, navigation, dirty, onSnapshot, open, onProtectionChange, inspect, config, locale, updateConfig, saveLayout }: { navigation?: PanelNavigation; config: unknown; locale: "en" | "zh"; updateConfig: (config: unknown) => void; saveLayout: () => void; node: TabNode; host: HTMLElement; dirty: Set<string>; onSnapshot: (drafts: WorkbenchDraft[]) => void; open: (type: string) => void; onProtectionChange: (value: boolean) => void; inspect: (view: DrawerView) => void }) {
  const callbacks = useRef({ onSnapshot, open }); callbacks.current = { onSnapshot, open };
  const id = node.getId();
  const onDraftChange = useCallback((value: boolean) => { if (value) dirty.add(id); else dirty.delete(id); onProtectionChange(dirty.size > 0); }, [dirty, id, onProtectionChange]);
  const onDraftSnapshot = useCallback((value: WorkbenchDraft[]) => callbacks.current.onSnapshot(value), []);
  const openPanel = useCallback((type: string) => callbacks.current.open(type), []);
  const hasOtherDrafts = useCallback(() => [...dirty].some(panelId => panelId !== id), [dirty, id]);
  const isVisible = useCallback(() => host.isConnected && host.getClientRects().length > 0 && getComputedStyle(host).visibility !== "hidden", [host]);
  const [activated, setActivated] = useState(false);
  useLayoutEffect(() => {
    if (activated) return;
    const activate = () => { if (isVisible()) setActivated(true); };
    activate();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(activate); observer.observe(host);
    return () => observer.disconnect();
  });
  // First visibility loads the module; later moves keep the same portal and drafts.
  return createPortal(activated ? <StudioPanel navigation={navigation} config={config} locale={locale} updateConfig={updateConfig} saveLayout={saveLayout} isVisible={isVisible} type={node.getComponent() ?? "missing"} onDraftChange={onDraftChange} onDraftSnapshot={onDraftSnapshot} hasOtherDrafts={hasOtherDrafts} open={openPanel} inspect={inspect} /> : null, host, id);
}
