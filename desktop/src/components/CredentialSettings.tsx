import { useCallback, useEffect, useRef, useState } from "react";
import { colors, typo, radius, space, btnPrimary, btnSecondary } from "../design";
import { bindNativeRuntimeSession, isLocalRuntimeSelected, listNativeProviderCredentials, type NativeCredentialNotice, type NativeCredentialStatus } from "../lib/nativeRuntime";
import { getRuntimeConfigVersion } from "../lib/api";
import { useRuntimeConfigVersion } from "../store";
import { defaultCredentialEnvironment, PROVIDER_TEMPLATES } from "./OnboardingWizard";
import { toast } from "./Toast";

export type CredentialStatus = NativeCredentialStatus;
export function credentialNameError(value: string): string {
  const name = value.trim();
  if (!name) return "Enter an environment variable name.";
  return /^[A-Z_][A-Z0-9_]{0,127}$/.test(name) ? "" : "Use uppercase letters, digits, and underscores.";
}
export function credentialSecretError(value: string): string {
  return value.trim().length >= 8 ? "" : "Enter a valid provider credential.";
}
function unusedName(provider: string, rows: CredentialStatus[]) {
  const base = defaultCredentialEnvironment(provider), names = new Set(rows.map(row => row.environment_name));
  let name = base, suffix = 2;
  while (names.has(name)) name = `${base}_${suffix++}`;
  return name;
}

/** The existing native credential manager; no key is sent to a Runtime API. */
export function CredentialSettings({ locale = "en", onDraftChange, hasOtherDrafts, onStored }: {
  locale?: "en" | "zh"; onDraftChange?: (dirty: boolean) => void; hasOtherDrafts?: () => boolean;
  onStored?: (notice: NativeCredentialNotice) => void;
} = {}) {
  const version = useRuntimeConfigVersion();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [credentials, setCredentials] = useState<CredentialStatus[]>([]);
  const [providerId, setProviderId] = useState("deepseek");
  const [environmentName, setEnvironmentName] = useState("DEEPSEEK_API_KEY");
  const [editing, setEditing] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [loading, setLoading] = useState(true);
  const [uncertain, setUncertain] = useState(false), [removing, setRemoving] = useState<string | null>(null);
  const [message, setMessage] = useState(""), [error, setError] = useState("");
  const active = useRef(false), operation = useRef(false), nameTouched = useRef(false), reads = useRef(0);
  const selectedProvider = useRef(providerId); selectedProvider.current = providerId;
  const retireReads = useCallback(() => { reads.current++; }, []);
  const protect = !!secret || busy || uncertain;
  useEffect(() => { onDraftChange?.(protect); }, [protect, onDraftChange]);
  useEffect(() => () => onDraftChange?.(false), [onDraftChange]);
  const refresh = useCallback(async () => {
    const sequence = ++reads.current;
    setLoading(true); setError("");
    try {
      const rows = await listNativeProviderCredentials();
      if (!active.current || version !== getRuntimeConfigVersion() || sequence !== reads.current) return;
      setCredentials(rows); setReady(true);
      if (!nameTouched.current) setEnvironmentName(unusedName(selectedProvider.current, rows));
    } catch (reason) {
      if (active.current && version === getRuntimeConfigVersion() && sequence === reads.current) {
        setReady(false); setCredentials([]); setError(reason instanceof Error ? reason.message : "Saved credential names are unavailable.");
      }
    } finally { if (active.current && version === getRuntimeConfigVersion() && sequence === reads.current) setLoading(false); }
  }, [version]);
  useEffect(() => {
    active.current = true; setReady(false); setSecret(""); setError(""); setMessage(""); setUncertain(false); setRemoving(null); operation.current = false;
    let retired = false;
    void Promise.resolve().then(() => { if (!retired) return refresh(); });
    return () => { retired = true; active.current = false; retireReads(); };
  }, [refresh, retireReads]);

  const mutate = async (removeName?: string) => {
    if (operation.current || !ready || uncertain) return;
    setError(""); setMessage("");
    if (hasOtherDrafts?.()) { setError(t("Save or cancel drafts in other panels before restarting the local Runtime.", "请先保存或取消其他面板中的草稿，再重启本地运行时。")); return; }
    const name = (removeName || environmentName).trim();
    if (!removeName) {
      if (credentialNameError(name)) { setError(t("Use an environment name with uppercase letters, digits and underscores.", "名称请使用大写字母、数字和下划线，且不能以数字开头。")); return; }
      if (credentialSecretError(secret)) { setError(t("Enter your complete Provider API key.", "请填写服务商提供的完整 API Key。")); return; }
      if (credentials.some(row => row.environment_name === name) && editing !== name) { setError(t("This name already exists. Choose Update on that saved key, or use another name.", "此名称已存在。请点击该密钥的“更新”，或使用其他名称。")); return; }
    }
    operation.current = true; setBusy(true);
    let dispatched = false;
    const command = removeName ? "remove_provider_credential" : "store_provider_credential";
    const args = removeName ? { environmentName: name } : { environmentName: name, secret };
    if (!removeName) setSecret("");
    try {
      const result = await bindNativeRuntimeSession(command, args, { isActive: () => active.current, onDispatched: () => { dispatched = true; } });
      // A verified local token rotation retires the old panel. Completion may
      // notify its current parent, but never a subsequently selected Controller.
      if (result.version !== getRuntimeConfigVersion() || !isLocalRuntimeSelected(result.endpoint)) return;
      const title = removeName ? t("Key removed", "密钥已移除") : t("Key saved", "密钥已保存");
      const detail = removeName ? t("Local Runtime restarted.", "本地运行时已重启。") : t(`Saved as ${name}. Continue in Models to add a connection.`, `已保存为 ${name}。请在“模型”中添加连接。`);
      toast({ title, message: detail, level: "success", durationMs: 8000 });
      if (!removeName) onStored?.({ environmentName: name, providerId: editing ? "" : providerId, endpoint: result.endpoint, version: result.version });
      if (active.current) { setEditing(null); nameTouched.current = false; setMessage(`${title}. ${detail}`); setRemoving(null); await refresh(); }
    } catch (reason) {
      if (active.current && version === getRuntimeConfigVersion()) {
        setUncertain(dispatched);
        setError(dispatched ? t("The key may have been saved, but Runtime reconnection was not confirmed. Inspect saved keys and Runtime diagnostics before another attempt.", "密钥可能已保存，但尚未确认运行时重新连接。请先核对已保存密钥和运行时诊断，再决定是否重试。") : reason instanceof Error ? reason.message : t("Credential operation could not start.", "未能启动密钥操作。"));
      }
    } finally { operation.current = false; if (active.current) setBusy(false); }
  };
  const remove = (name: string) => {
    if (operation.current || uncertain) return;
    if (removing !== name) { setRemoving(name); return; }
    void mutate(name);
  };
  return <section aria-label={t("Secure API keys", "安全 API 密钥")} style={{ display: "grid", gap: space.sm }}>
    <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: space.sm }}><strong>{t("Saved keys", "已保存的密钥")}</strong><button style={btnSecondary} disabled={busy || loading} onClick={() => void refresh()}>{t("Refresh keys", "刷新密钥")}</button></header>
    {loading && <p role="status">{t("Checking local credential storage…", "正在检查本机凭据存储…")}</p>}
    {busy && <p role="status" aria-live="polite">{t("Saving changes and restarting the local Runtime… Please wait.", "正在保存并重启本地运行时，请稍候…")}</p>}
    {error && <p role="alert" style={{ color: colors.danger }}>{error === "Local Runtime management requires the desktop application." ? t("Use the desktop application to save keys here. A remote Controller uses its own credential backend.", "请在桌面应用中保存密钥。远程 Controller 使用其主机上的凭据后端。") : /Select the local Runtime/.test(error) ? t("Connect this desktop to its local Runtime before managing keys.", "请先连接本机运行时，再管理密钥。") : error}</p>}
    {message && <p role="status">{message}</p>}
    {uncertain && <button style={btnSecondary} onClick={() => { setUncertain(false); setMessage(t("Original state inspected. Enter a key only if another update is intended.", "已核对原始状态。确需再次更新时，请重新填写密钥。")); }}>{t("I inspected the original state", "已核对原始状态")}</button>}
    {!loading && ready && !credentials.length && <p>{t("No saved API keys. Add one below; a model connection is configured separately.", "尚未保存 API 密钥。先在下方添加，再配置模型连接。")}</p>}
    {credentials.map(credential => <article key={credential.environment_name} style={{ display: "flex", gap: space.sm, alignItems: "center", padding: space.md, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md }}>
      <div style={{ flex: 1, minWidth: 0 }}><code>{credential.environment_name}</code><small style={{ display: "block", color: colors.textSecondary }}>{credential.stored ? t("Saved locally · inference not verified", "已在本机保存 · 尚未验证推理") : t("Reference unavailable", "引用不可用")}</small></div>
      <button style={btnSecondary} disabled={busy || uncertain || !!secret} onClick={() => { nameTouched.current = true; setEditing(credential.environment_name); setEnvironmentName(credential.environment_name); setError(""); }}>{t("Update", "更新")}</button>
      <button style={btnSecondary} disabled={busy || uncertain || !!secret} onClick={() => remove(credential.environment_name)}>{removing === credential.environment_name ? t("Confirm remove", "确认移除") : t("Remove", "移除")}</button>
    </article>)}
    <form aria-label={t("API key form", "API 密钥表单")} onSubmit={event => { event.preventDefault(); void mutate(); }}>
      <fieldset disabled={!ready || busy || uncertain} style={{ display: "grid", gap: space.sm, border: 0, padding: 0, minWidth: 0 }}>
        <div style={{ display: "flex", gap: space.sm, alignItems: "center" }}><strong>{editing ? t("Update saved key", "更新已保存密钥") : t("Add API key", "添加 API 密钥")}</strong>{editing && <button type="button" style={btnSecondary} onClick={() => { setEditing(null); setSecret(""); nameTouched.current = false; setEnvironmentName(unusedName(providerId, credentials)); }}>{t("Add another key", "另存新密钥")}</button>}</div>
        {!editing && <label>{t("Provider", "服务商")} <select aria-label={t("Key Provider", "密钥服务商")} value={providerId} onChange={event => { setProviderId(event.target.value); nameTouched.current = false; setEnvironmentName(unusedName(event.target.value, credentials)); setSecret(""); }}>
          {PROVIDER_TEMPLATES.filter(preset => preset.credentialType !== "none" && !preset.unsupportedProtocol).map(preset => <option key={preset.providerId} value={preset.providerId}>{preset.displayName}</option>)}
        </select></label>}
        <label style={{ display: "grid", gap: space.xs }}>{t("API key", "API 密钥")}<input aria-label={t("Provider credential", "服务商密钥")} type="password" value={secret} onChange={event => setSecret(event.target.value)} autoComplete="new-password" style={{ padding: space.sm, border: `1px solid ${colors.border}`, borderRadius: radius.sm }} /></label>
        <details><summary>{t("Credential name (advanced)", "密钥名称（高级）")}</summary><label>{t("Environment name", "环境变量名称")} <input value={environmentName} disabled={!!editing} onChange={event => { nameTouched.current = true; setEnvironmentName(event.target.value.toUpperCase()); }} autoComplete="off" spellCheck={false} /></label><small>{t("References use env:NAME; the actual key stays in Windows Credential Manager.", "引用格式为 env:名称；实际密钥保存在 Windows 凭据管理器中。")}</small></details>
        <small style={{ color: colors.textSecondary, fontSize: typo.xs }}>{t("Saving restarts the local Runtime. Save other drafts first. It does not test a model.", "保存会重启本地运行时，请先保存其他草稿；此操作不测试模型。")}</small>
        <button type="submit" style={{ ...btnPrimary, justifySelf: "start" }}>{busy ? t("Saving…", "正在保存…") : editing ? t("Update key", "更新密钥") : t("Save key", "保存密钥")}</button>
      </fieldset>
    </form>
  </section>;
}
