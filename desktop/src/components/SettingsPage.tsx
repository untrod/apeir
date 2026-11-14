import { lazy, Suspense, useCallback, useEffect, useId, useState } from "react";
import { useTheme } from "../theme";
import { resetUIState } from "../lib/migration";
import { CredentialSettings } from "./CredentialSettings";
import { getRuntimeConfigVersion } from "../lib/api";
import type { NativeCredentialNotice } from "../lib/nativeRuntime";
import "./SettingsPage.css";
const DeveloperPlatform = lazy(() => import("./DeveloperPlatform").then(module => ({ default: module.DeveloperPlatform })));

/** One settings surface for the legacy route and the in-workspace dialog. */
export function SettingsPage({ onOpenModels, onOpenLayouts, onOpenApprovals, onClose, onDraftChange, hasOtherDrafts, hasProtectedChanges, initialSection = "general", initialModelSection = "models", notice = "", preferredCredential, onCredentialStored }: {
  onOpenModels?: () => void; onOpenLayouts?: () => void; onClose?: () => void;
  onDraftChange?: (dirty: boolean) => void; hasOtherDrafts?: () => boolean; hasProtectedChanges?: () => boolean;
  initialSection?: "general" | "models";
  initialModelSection?: "models" | "credentials"; onOpenApprovals?: () => void;
  preferredCredential?: NativeCredentialNotice | null; onCredentialStored?: (notice: NativeCredentialNotice) => void;
  notice?: string;
}) {
  const { locale, setLocale, mode, setMode } = useTheme();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [section, setSection] = useState<string>(initialSection);
  const [modelSection, setModelSection] = useState(initialModelSection);
  const [modelsVisited, setModelsVisited] = useState(initialSection === "models" && initialModelSection === "models");
  const [credentialsVisited, setCredentialsVisited] = useState(initialSection === "models" && initialModelSection === "credentials");
  const [recentCredential, setRecentCredential] = useState<NativeCredentialNotice | null>(null);
  const [developer, setDeveloper] = useState(() => localStorage.getItem("nous_developer_mode") === "1");
  const [message, setMessage] = useState("");
  const [credentialDraft, setCredentialDraft] = useState(false);
  const [modelDraft, setModelDraft] = useState(false);
  // A verified native session rotation can remount this view before the
  // credential completion selects Models. Honour that explicit parent request.
  useEffect(() => {
    setSection(initialSection); setModelSection(initialModelSection);
    if (initialSection === "models") {
      if (initialModelSection === "models") setModelsVisited(true); else setCredentialsVisited(true);
    }
  }, [initialSection, initialModelSection]);
  const protect = useCallback((value: boolean) => { setCredentialDraft(value); }, []);
  const protectModel = useCallback((value: boolean) => { setModelDraft(value); }, []);
  useEffect(() => { onDraftChange?.(credentialDraft || modelDraft); }, [credentialDraft, modelDraft, onDraftChange]);
  useEffect(() => () => onDraftChange?.(false), [onDraftChange]);
  const credential = preferredCredential || recentCredential;
  const currentCredential = credential?.version === getRuntimeConfigVersion() ? credential : null;
  const showModelSection = (next: "models" | "credentials") => {
    if (next === modelSection) return;
    if (credentialDraft || modelDraft) { setMessage(t("Save or cancel the current changes before switching model settings.", "请先保存或取消当前修改，再切换模型设置。")); return; }
    setMessage(""); setModelSection(next);
    if (next === "models") setModelsVisited(true); else setCredentialsVisited(true);
  };
  const credentialStored = (value: NativeCredentialNotice) => {
    if (value.version !== getRuntimeConfigVersion()) return;
    setRecentCredential(value); setModelSection("models"); setModelsVisited(true); onCredentialStored?.(value);
  };
  const id = useId();
  const update = (action: () => void) => { try { action(); setMessage(""); } catch { setMessage(t("Preferences could not be saved. Previous settings remain available.", "偏好设置未能保存，原有设置仍可使用。")); } };
  const sections = [
    { id: "general", en: "General", zh: "通用" },
    { id: "models", en: "Models & credentials", zh: "模型与凭据" },
    { id: "advanced", en: "Advanced", zh: "高级" },
  ];
  return <section className="app-settings" aria-label={t("Application settings", "应用设置")}>
    <header><h2>{t("Settings", "设置")}</h2>{onClose && <button aria-label={t("Close settings", "关闭设置")} onClick={onClose}>×</button>}</header>
    <div className="app-settings-body">
      <nav role="tablist" aria-label={t("Settings categories", "设置分类")} aria-orientation="vertical">
        {sections.map(item => <button key={item.id} id={`${id}-${item.id}`} role="tab" aria-selected={section === item.id} aria-controls={`${id}-${item.id}-body`} tabIndex={section === item.id ? 0 : -1} onKeyDown={event => {
          if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const index = sections.findIndex(value => value.id === item.id);
          const next = event.key === "Home" ? 0 : event.key === "End" ? sections.length - 1 : (index + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + sections.length) % sections.length;
          setSection(sections[next].id); if (sections[next].id === "models") { if (modelSection === "models") setModelsVisited(true); else setCredentialsVisited(true); }
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
        }} onClick={() => { setSection(item.id); if (item.id === "models") { if (modelSection === "models") setModelsVisited(true); else setCredentialsVisited(true); } }}>{t(item.en, item.zh)}</button>)}
      </nav>
      <main>
        <section role="tabpanel" id={`${id}-general-body`} aria-labelledby={`${id}-general`} hidden={section !== "general"}>
          <h3>{t("Appearance & language", "外观与语言")}</h3>
          <label className="app-settings-row"><span>{t("Language", "语言")}</span><select aria-label="Studio language" value={locale} onChange={event => update(() => setLocale(event.target.value as "en" | "zh"))}><option value="en">English</option><option value="zh">中文</option></select></label>
          <label className="app-settings-row"><span>{t("Theme", "主题")}</span><select aria-label="Studio theme" value={mode} onChange={event => update(() => setMode(event.target.value as "light" | "dark" | "system"))}><option value="system">{t("System", "跟随系统")}</option><option value="dark">{t("Dark", "深色")}</option><option value="light">{t("Light", "浅色")}</option></select></label>
          {onOpenLayouts && <div className="app-settings-row"><span>{t("Saved layouts", "已保存的布局")}</span><button onClick={onOpenLayouts}>{t("Open layout library", "打开布局库")}</button></div>}
        </section>
        <section role="tabpanel" id={`${id}-models-body`} aria-labelledby={`${id}-models`} hidden={section !== "models"}>
          <h3>{t("Models & credentials", "模型与凭据")}</h3>
          <div className="app-settings-model-tabs" role="tablist" aria-label={t("Model settings", "模型设置")}>
            {(["models", "credentials"] as const).map((item, index) => <button key={item} id={`${id}-${item}-tab`} role="tab" aria-selected={modelSection === item} aria-controls={`${id}-${item}-settings`} tabIndex={modelSection === item ? 0 : -1} onClick={() => showModelSection(item)} onKeyDown={event => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index;
              if (credentialDraft || modelDraft) { showModelSection(next ? "credentials" : "models"); return; }
              showModelSection(next ? "credentials" : "models");
              event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
            }}>{item === "models" ? t("Models", "模型") : t("API keys", "API 密钥")}</button>)}
          </div>
          <div role="tabpanel" id={`${id}-models-settings`} aria-labelledby={`${id}-models-tab`} hidden={modelSection !== "models"}>
            {currentCredential && <p role="status">{t("Key saved. Add a model below; its reference is ready to select.", "密钥已保存。请在下方添加模型，可直接选择对应密钥。")}</p>}
            {modelsVisited && <Suspense fallback={<p role="status">{t("Loading models…", "正在加载模型…")}</p>}><DeveloperPlatform modelsOnly manageProviders modelConnectionsOnly locale={locale} onDraftChange={protectModel} onOpenCredentials={() => showModelSection("credentials")} onOpenApprovals={onOpenApprovals} preferredCredential={currentCredential} /></Suspense>}
            {onOpenModels && <button onClick={onOpenModels}>{t("Open Models workspace", "打开模型工作区")}</button>}
          </div>
          <div role="tabpanel" id={`${id}-credentials-settings`} aria-labelledby={`${id}-credentials-tab`} hidden={modelSection !== "credentials"}>{credentialsVisited && <CredentialSettings locale={locale} onDraftChange={protect} hasOtherDrafts={() => modelDraft || !!hasOtherDrafts?.()} onStored={credentialStored} />}</div>
        </section>
        <section role="tabpanel" id={`${id}-advanced-body`} aria-labelledby={`${id}-advanced`} hidden={section !== "advanced"}>
          <h3>{t("Advanced", "高级")}</h3>
          <label className="app-settings-row"><span>{t("Developer mode", "开发者模式")}</span><input type="checkbox" checked={developer} onChange={event => update(() => { const enabled = event.target.checked; localStorage.setItem("nous_developer_mode", enabled ? "1" : "0"); setDeveloper(enabled); })} /></label>
          <div className="app-settings-row"><span>{t("Reset cached interface state", "重置界面缓存")}<small>{t("Workspace files, credentials and Runtime history are retained.", "保留工作区文件、凭据和运行历史。")}</small></span><button disabled={credentialDraft || modelDraft || hasProtectedChanges?.()} onClick={() => {
            if (credentialDraft || modelDraft || hasProtectedChanges?.()) return;
            if (window.confirm(t("Reset interface layouts and reload?", "重置界面布局并重新载入？"))) { resetUIState(); window.location.reload(); }
          }}>{t("Reset…", "重置…")}</button></div>
        </section>
        {(message || notice) && <p role="alert">{message || notice}</p>}
      </main>
    </div>
  </section>;
}
