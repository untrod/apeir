import { useCallback, useId, useMemo, useRef, useState } from "react";
import type { WorkbenchDraft } from "../DeveloperWorkbench";
import type { PanelProps } from "./StudioPanels";
import { StudioPackages } from "./StudioPackages";
import { StudioSkills } from "./StudioSkills";
import { useStudioSnapshot } from "./StudioData";

type Kind = "skills" | "ui" | "tools";
const kinds: Kind[] = ["skills", "ui", "tools"];

/** Presentation only. Skills/ExtensionRegistry/Governance retain all state. */
export function StudioExtensions(props: PanelProps) {
  const { locale, onDraftChange, onDraftSnapshot, isVisible } = props;
  const { refresh } = useStudioSnapshot();
  const [mode, setMode] = useState<"installed" | "discover">("installed");
  const [kind, setKind] = useState<Kind | "all">("all"), [query, setQuery] = useState("");
  const dirty = useRef<Record<string, boolean>>({}), drafts = useRef<Record<string, WorkbenchDraft[]>>({});
  const identity = useId();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const callbacks = useMemo(() => Object.fromEntries(kinds.map(key => [key, {
    onDraftChange: (value: boolean) => {
      const previous = Object.values(dirty.current).some(Boolean);
      dirty.current[key] = value;
      const next = Object.values(dirty.current).some(Boolean);
      if (next !== previous) onDraftChange(next);
    },
    onDraftSnapshot: (value: WorkbenchDraft[]) => {
      if (JSON.stringify(drafts.current[key] || []) === JSON.stringify(value)) return;
      drafts.current[key] = value; onDraftSnapshot(Object.values(drafts.current).flat());
    },
  }])) as Record<Kind, Pick<PanelProps, "onDraftChange" | "onDraftSnapshot">>, [onDraftChange, onDraftSnapshot]);
  const skillsVisible = useCallback(() => isVisible() && (kind === "all" || kind === "skills"), [isVisible, kind]);
  const uiVisible = useCallback(() => isVisible() && (kind === "all" || kind === "ui"), [isVisible, kind]);
  const toolsVisible = useCallback(() => isVisible() && (kind === "all" || kind === "tools"), [isVisible, kind]);
  return <section className="studio-extensions studio-projection" aria-label="Extensions">
    <header><strong>{t("Extensions", "扩展")}</strong><button onClick={() => refresh(["operations", "extensions"])}>{t("Refresh", "刷新")}</button></header>
    <div className="studio-extension-tabs" role="tablist" aria-label={t("Extension library", "扩展库")}>
      {(["installed", "discover"] as const).map((tab, index) => <button key={tab} id={`${identity}-${tab}`} role="tab" aria-selected={mode === tab} aria-controls={`${identity}-content`} tabIndex={mode === tab ? 0 : -1} onClick={() => setMode(tab)} onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); const next = event.key === "Home" ? "installed" : event.key === "End" ? "discover" : index === 0 ? "discover" : "installed";
        setMode(next); document.getElementById(`${identity}-${next}`)?.focus();
      }}>{tab === "installed" ? t("Installed", "已安装") : t("Discover", "发现与安装")}</button>)}
    </div>
    <div className="studio-extension-filters"><label className="studio-extension-search">{t("Search", "搜索")}<input type="search" placeholder={t("Find an extension", "查找扩展")} value={query} onChange={event => setQuery(event.target.value)} /></label><label>{t("Type", "类型")}<select aria-label={t("Type", "类型")} value={kind} onChange={event => setKind(event.target.value as Kind | "all")}><option value="all">{t("All", "全部")}</option><option value="skills">{t("Skills", "技能")}</option><option value="tools">{t("Tools", "工具")}</option><option value="ui">{t("Interface", "界面")}</option></select></label></div>
    <div role="tabpanel" id={`${identity}-content`} aria-labelledby={`${identity}-${mode}`}>
      <div hidden={kind !== "all" && kind !== "skills"}><StudioSkills {...props} {...callbacks.skills} mode={mode} query={query} onInstalled={() => setMode("installed")} isVisible={skillsVisible} /></div>
      <div hidden={kind !== "all" && kind !== "ui"}><StudioPackages {...props} {...callbacks.ui} kind="ui" mode={mode} query={query} onInstalled={() => setMode("installed")} isVisible={uiVisible} /></div>
      <div hidden={kind !== "all" && kind !== "tools"}><StudioPackages {...props} {...callbacks.tools} kind="tools" mode={mode} query={query} onInstalled={() => setMode("installed")} isVisible={toolsVisible} /></div>
    </div>
  </section>;
}
