import { useCallback, useEffect, useRef, useState } from "react";
import { btnPrimary, btnSecondary, colors, input, space } from "../design";
import { ApiError, api, getRuntimeConfigVersion, governedStudioMutation, testModel, type ModelLabSnapshot, type ModelTestResult } from "../lib/api";
import { useRuntimeConfigVersion } from "../store";
import { defaultCredentialEnvironment, defaultModelAssignments, PROVIDER_TEMPLATES } from "./OnboardingWizard";
import { listNativeProviderCredentials, type NativeCredentialNotice, type NativeCredentialStatus } from "../lib/nativeRuntime";

const credentialReference = /^env:[A-Za-z_][A-Za-z0-9_]{0,127}$/;

type SavedConfiguration = { name: string; api_base_url: string; model: string; has_reference: boolean };
type ProviderSummary = { id: string; name: string; health?: { status?: string }; configuration?: SavedConfiguration };
type Draft = { id: string; name: string; endpoint: string; model: string; credential: string; clearCredential: boolean; original?: SavedConfiguration };

/** Presentation over the existing Provider lifecycle; credentials remain references. */
export function ProviderSettings({ locale = "en", models, modelsReady = true, onChanged, onOpenApprovals, onOpenCredentials, onDraftChange, preferredCredential }: {
  locale?: "en" | "zh"; models: ModelLabSnapshot["models"]; modelsReady?: boolean; onChanged: () => Promise<void>; onOpenApprovals?: () => void; onOpenCredentials?: () => void; onDraftChange?: (dirty: boolean) => void;
  preferredCredential?: NativeCredentialNotice | null;
}) {
  const version = useRuntimeConfigVersion();
  const active = useRef(false), inFlight = useRef(false), reads = useRef(0);
  const referenceTouched = useRef(false);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [providerLoading, setProviderLoading] = useState(true);
  const [savedKeys, setSavedKeys] = useState<NativeCredentialStatus[]>([]);
  const [keyError, setKeyError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [message, setMessage] = useState(""), [removing, setRemoving] = useState("");
  const [templateId, setTemplateId] = useState("openai");
  const [modelId, setModelId] = useState("");
  const [result, setResult] = useState<ModelTestResult | null>(null);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const t = useCallback((en: string, zh: string) => locale === "zh" ? zh : en, [locale]);
  useEffect(() => { onDraftChange?.(!!draft || busy); }, [draft, busy, onDraftChange]);
  useEffect(() => () => onDraftChange?.(false), [onDraftChange]);
  const current = useCallback(() => {
    if (!active.current || getRuntimeConfigVersion() !== version) throw new Error("Controller changed; review the original request.");
  }, [version]);
  const refresh = useCallback(async () => {
    const sequence = ++reads.current;
    current(); setProviders([]); setResult(null); setProviderLoading(true);
    const rows = await api<ProviderSummary[]>("/api/v1/providers");
    current();
    if (!Array.isArray(rows) || rows.some(row => !row || typeof row.id !== "string" || typeof row.name !== "string" || row.configuration && (
      typeof row.configuration !== "object" || [row.configuration.name, row.configuration.api_base_url, row.configuration.model].some(value => typeof value !== "string") || typeof row.configuration.has_reference !== "boolean"
    )) || new Set(rows.map(row => row.id)).size !== rows.length) {
      throw new Error("Provider metadata is unavailable.");
    }
    if (sequence === reads.current) { setProviders(rows); setProviderLoading(false); }
  }, [current]);
  useEffect(() => {
    let retired = false;
    active.current = true;
    inFlight.current = false; setBusy(false); setDraft(null); setResult(null); setModelId(""); setRemoving(""); setError(""); setMessage(""); setApprovalRequired(false);
    void Promise.resolve().then(() => { if (!retired) return refresh(); }).catch(() => { if (!retired && active.current && getRuntimeConfigVersion() === version) { setProviderLoading(false); setError("Provider metadata is unavailable."); } });
    return () => { retired = true; active.current = false; };
  }, [refresh, version]);
  useEffect(() => {
    if (modelsReady && modelId && !models.some(model => model.model_id === modelId)) {
      setModelId(""); setResult(null);
    }
  }, [models, modelsReady, modelId]);
  const draftId = draft?.id;
  const editingSaved = !!draft?.original;
  useEffect(() => {
    setSavedKeys([]); setKeyError("");
    if (!draftId || !("__TAURI_INTERNALS__" in window)) return;
    let retired = false;
    void listNativeProviderCredentials().then(rows => {
      if (retired || getRuntimeConfigVersion() !== version) return;
      const available = rows.filter(row => row.stored); setSavedKeys(available);
      if (!editingSaved) {
        const preferred = preferredCredential?.version === version && preferredCredential.providerId === templateId ? preferredCredential.environmentName : defaultCredentialEnvironment(templateId);
        if (!referenceTouched.current && available.some(row => row.environment_name === preferred)) setDraft(previous => previous && !previous.original && !previous.credential ? { ...previous, credential: `env:${preferred}` } : previous);
      }
    }).catch(() => { if (!retired && getRuntimeConfigVersion() === version) setKeyError(t("Saved local keys could not be read. Use a reference or open key settings.", "未能读取本机密钥名单。可填写引用，或打开密钥设置。")); });
    return () => { retired = true; };
  }, [draftId, editingSaved, templateId, version, preferredCredential, t]);

  const perform = async (action: () => Promise<void>) => {
    if (inFlight.current) return;
    current(); inFlight.current = true; setBusy(true); setError(""); setMessage(""); setApprovalRequired(false);
    try { await action(); }
    catch (cause) {
      if (active.current && getRuntimeConfigVersion() === version) {
        setProviderLoading(false);
        setError(cause instanceof Error ? cause.message : "Request failed; inspect original state before retrying.");
        setApprovalRequired(cause instanceof ApiError && cause.code.includes("APPROVAL_REQUIRED"));
      }
    } finally {
      if (active.current && getRuntimeConfigVersion() === version) { inFlight.current = false; setBusy(false); }
    }
  };
  const newDraft = (id: string) => {
    referenceTouched.current = false;
    const preset = PROVIDER_TEMPLATES.find(item => item.providerId === id);
    setResult(null);
    setTemplateId(id); setDraft({ id, name: preset?.displayName || "", endpoint: preset?.defaultBaseUrl || "", model: preset ? defaultModelAssignments(id, ["chat"]).chat || "" : "", credential: "", clearCredential: false });
    setRemoving(""); setError(""); setMessage("");
  };
  const save = async () => {
    if (!draft) return;
    const originalDraft = draft;
    await perform(async () => {
      if (!/^[A-Za-z0-9._-]+$/.test(draft.id) || !draft.name.trim() || !draft.endpoint.trim() || !draft.model.trim()) throw new Error(t("Complete Provider ID, name, endpoint and model ID.", "请填写服务商 ID、名称、端点和模型 ID。"));
      if (draft.credential && !credentialReference.test(draft.credential)) throw new Error(t("Enter an env:NAME reference, never an API key.", "请输入 env:NAME 凭据引用，不要粘贴 API Key。"));
      if (!draft.original && providers.some(row => row.id === draft.id)) throw new Error(t("This Provider already exists. Choose Edit.", "此服务商已存在，请选择编辑。"));
      const changes: Record<string, unknown> = {};
      for (const [key, value] of Object.entries({ name: draft.name.trim(), api_base_url: draft.endpoint.trim(), model: draft.model.trim() })) {
        if (!draft.original || value !== draft.original[key as keyof SavedConfiguration]) changes[key] = value;
      }
      if (draft.credential || draft.clearCredential || !draft.original) changes.credential_ref = draft.clearCredential ? "" : draft.credential;
      if (!Object.keys(changes).length) { setMessage(t("No configuration changes.", "配置没有变化。")); return; }
      // Validation does no inference; mutation remains a separately governed request.
      if (!draft.original) {
        const preset = PROVIDER_TEMPLATES.find(item => item.providerId === templateId);
        const body = { ...changes, provider_id: draft.id, capabilities: preset?.supportedCapabilities || ["chat"] };
        await governedStudioMutation("/api/v1/providers/validate", body, current);
        current();
        await governedStudioMutation("/api/v1/providers", body, current);
      } else {
        await governedStudioMutation(`/api/v1/providers/${encodeURIComponent(draft.id)}`, changes, current, "PATCH");
      }
      current(); setDraft(previous => previous === originalDraft ? null : previous);
      setMessage(t("Configuration saved. Inference has not been tested.", "配置已保存，尚未测试推理。"));
      await refresh(); current(); await onChanged();
    });
  };
  const remove = (id: string) => {
    if (draft) return;
    if (removing !== id) { setRemoving(id); return; }
    void perform(async () => {
      await governedStudioMutation(`/api/v1/providers/${encodeURIComponent(id)}`, {}, current, "DELETE");
      current(); setRemoving(""); setDraft(null);
      setMessage(t("Provider removed. Its credential and admitted requests are unchanged.", "服务商已移除；独立凭据及已接纳的请求不受影响。"));
      await refresh(); current(); await onChanged();
    });
  };
  const test = () => void perform(async () => {
    if (draft) throw new Error(t("Save or cancel configuration changes before testing.", "请先保存或取消配置修改，再测试模型。"));
    if (!modelsReady || !models.some(model => model.model_id === modelId)) throw new Error("Select a currently registered model.");
    setResult(null);
    try {
      const response = await testModel(modelId);
      current();
      if (response.model_id !== modelId || response.healthy && (response.selected_model_id !== modelId || !response.request_id)) throw new Error("Model response identity changed; inspect original usage.");
      setResult(response);
      await onChanged();
    } catch (cause) {
      current(); setMessage(t("No automatic retry. Inspect original usage before submitting a new test.", "不会自动重试；提交新测试前请核对原始用量。")); throw cause;
    }
  });
  const rowStyle = { display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" as const };
  const measured = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : "UNKNOWN";
  const localTemplate = !draft?.original && PROVIDER_TEMPLATES.find(item => item.providerId === templateId)?.credentialType === "none";
  const modelGroups = [
    { label: t("Local models", "本地模型"), values: models.filter(model => ["local_model", "local_service"].includes(model.endpoint_type)) },
    { label: t("API models", "API 模型"), values: models.filter(model => model.endpoint_type === "cloud_api") },
    { label: t("Other endpoints", "其他端点"), values: models.filter(model => !["local_model", "local_service", "cloud_api"].includes(model.endpoint_type)) },
  ];
  const draftField = (key: "id" | "name" | "endpoint" | "model" | "credential", en: string, zh: string) => draft && <label key={key}>{t(en, zh)} <input aria-label={t(en, zh)} autoComplete="off" spellCheck={false} style={input} type={key === "credential" && !!draft.credential && !credentialReference.test(draft.credential) ? "password" : "text"} disabled={busy || key === "id" && !!draft.original} value={draft[key]} onChange={event => { if (key === "credential") referenceTouched.current = true; setDraft(previous => previous && ({ ...previous, [key]: event.target.value })); }} placeholder={key === "credential" ? draft.original ? t("Blank keeps the existing reference", "留空保留现有引用") : `env:${templateId === "deepseek" ? "DEEPSEEK" : "OPENAI"}_API_KEY` : key === "model" && templateId === "deepseek" ? "deepseek-chat" : undefined} /></label>;
  return <section aria-label={t("Provider settings", "服务商设置")} style={{ display: "grid", gap: space.sm, marginBottom: space.lg }}>
    <div style={rowStyle}><strong>{t("Providers", "服务商")}</strong>
      <button style={btnPrimary} disabled={busy || !!draft} onClick={() => newDraft(preferredCredential?.version === version && PROVIDER_TEMPLATES.some(preset => preset.providerId === preferredCredential.providerId && !preset.unsupportedProtocol) ? preferredCredential.providerId : "openai")}>{t("Add Provider", "添加服务商")}</button>
      <button style={btnSecondary} disabled={busy} onClick={() => void perform(async () => { await refresh(); current(); await onChanged(); })}>{t("Refresh Providers", "刷新服务商")}</button>
      {onOpenCredentials && <button style={btnSecondary} onClick={onOpenCredentials}>{t("Manage credentials", "管理凭据")}</button>}
    </div>
    <h3 style={{ margin: 0 }}>{t("Registered models", "已注册模型")}</h3>
    <div style={{ overflowX: "auto" }}><table aria-label={t("Registered models", "已注册模型")} style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
      <thead><tr><th>{t("Model", "模型")}</th><th>{t("Provider", "服务商")}</th><th>{t("Status", "状态")}</th></tr></thead>
      <tbody>{!modelsReady ? <tr><td colSpan={3} role="status">{t("Model catalog is loading or unavailable.", "模型名单正在加载或暂不可用。")}</td></tr> : !models.length ? <tr><td colSpan={3}>{t("No registered models. Save a connection below; saving an API key alone does not register a model.", "尚无已注册模型。请添加并保存下方连接；仅保存 API 密钥不会注册模型。")}</td></tr> : models.map(model => <tr key={model.model_id}><td><strong>{model.display_name}</strong><small style={{ display: "block" }}><code>{model.model_id}</code></small></td><td>{model.provider_id}<small style={{ display: "block" }}>{["local_model", "local_service"].includes(model.endpoint_type) ? t("Local", "本地") : model.endpoint_type === "cloud_api" ? "API" : t("Other", "其他")}</small></td><td>{model.health || "UNKNOWN"}<small style={{ display: "block" }}>{t("Reported status", "报告状态")} · {model.state || "UNKNOWN"}</small></td></tr>)}</tbody>
    </table></div>
    {busy && <p role="status" aria-live="polite">{t("Applying the request… Please wait; do not submit again.", "正在处理请求，请稍候，不要重复提交。")}</p>}
    {error && <p role="alert" style={{ color: colors.danger }}>{error}</p>}
    {approvalRequired && onOpenApprovals && <button style={{ ...btnSecondary, justifySelf: "start" }} onClick={onOpenApprovals}>{t("Open original approvals", "查看原始审批")}</button>}
    {message && <p role="status">{message}</p>}
    <h3 style={{ margin: 0 }}>{t("Saved connections", "已保存连接")}</h3>
    {providerLoading ? <p role="status">{t("Loading connections…", "正在加载连接…")}</p> : !providers.length && !error && <p>{t("No saved connections. Add a Provider to get started.", "尚无已保存连接。请先添加服务商。")}</p>}
    {providers.map(provider => <div key={provider.id} style={rowStyle}>
      <span style={{ flex: 1 }}>{provider.name} <code>{provider.id}</code> · {t("Reported status", "报告状态")}: {typeof provider.health?.status === "string" ? provider.health.status : "UNKNOWN"}</span>
      <button style={btnSecondary} disabled={busy || !provider.configuration || !!draft} aria-label={`${t("Edit", "编辑")} ${provider.id}`} onClick={() => {
        const config = provider.configuration!;
        setDraft({ id: provider.id, name: config.name, endpoint: config.api_base_url, model: config.model, credential: "", clearCredential: false, original: config }); setRemoving(""); setMessage(""); setResult(null);
      }}>{t("Edit", "编辑")}</button>
      <button style={btnSecondary} disabled={busy || !!draft || !provider.configuration} aria-label={`${removing === provider.id ? t("Confirm remove", "确认移除") : t("Remove", "移除")} ${provider.id}`} onClick={() => remove(provider.id)}>{removing === provider.id ? t("Confirm remove", "确认移除") : t("Remove", "移除")}</button>
      {provider.configuration && <small style={{ width: "100%" }}>{provider.configuration.model || "UNKNOWN"} · {provider.configuration.api_base_url || "UNKNOWN"} · {provider.configuration.has_reference ? t("Reference saved", "引用已保存") : t("No saved reference", "无已保存引用")}</small>}
    </div>)}
    {draft && <form onSubmit={event => { event.preventDefault(); void save(); }} style={{ display: "grid", gap: space.sm }}>
      {!draft.original && <label>{t("Protocol template", "协议模板")} <select aria-label={t("Protocol template", "协议模板")} value={templateId} disabled={busy} onChange={event => newDraft(event.target.value)} style={input}>
        {PROVIDER_TEMPLATES.map(preset => <option key={preset.providerId} value={preset.providerId} disabled={preset.unsupportedProtocol}>{preset.displayName}{preset.unsupportedProtocol ? " · UNSUPPORTED" : ""}</option>)}
      </select></label>}
      {draftField("model", "Vendor model ID", "厂商模型 ID")}
      {!localTemplate && <>{savedKeys.length > 0 && <label>{t("Saved API key", "已保存的 API 密钥")} <select aria-label={t("Saved API key", "已保存的 API 密钥")} disabled={busy} style={input} value={savedKeys.some(row => `env:${row.environment_name}` === draft.credential) ? draft.credential : ""} onChange={event => { referenceTouched.current = true; setDraft(previous => previous && ({ ...previous, credential: event.target.value, clearCredential: false })); }}><option value="">{draft.original ? t("Keep existing reference / enter another", "保留原引用 / 输入其他引用") : t("Choose a saved key", "选择已保存密钥")}</option>{savedKeys.map(row => <option key={row.environment_name} value={`env:${row.environment_name}`}>{row.environment_name}</option>)}</select></label>}{draftField("credential", "Credential reference", "凭据引用")}<small>{t("Select a saved key, or enter env:NAME. Never paste an API key in this form.", "可直接选择已保存密钥，或填写 env:名称。请勿在此粘贴真实 API Key。")}</small>{keyError && <p role="status">{keyError}</p>}</>}
      {localTemplate && <small>{t("Connect an already-running local service using its installed model ID.", "填写已运行本地服务中的模型 ID；此操作不会下载或启动模型。")}</small>}
      <details className="provider-advanced" open={!draft.original && templateId === "openai_compatible"}>
        <summary>{t("Connection settings", "连接设置")}</summary>
        {draftField("endpoint", "Endpoint", "端点")}
        {draftField("name", "Name", "名称")}
        {draftField("id", "Provider ID", "服务商 ID")}
        {localTemplate && draftField("credential", "Optional credential reference", "可选凭据引用")}
        {draft.original && <label><input type="checkbox" checked={draft.clearCredential} disabled={busy} onChange={event => setDraft(previous => previous && ({ ...previous, clearCredential: event.target.checked }))} />{t("Clear saved credential reference", "清除已保存的凭据引用")}</label>}
      </details>
      <div style={rowStyle}><button type="submit" disabled={busy} style={btnPrimary}>{t("Save Provider", "保存服务商")}</button><button type="button" disabled={busy} style={btnSecondary} onClick={() => setDraft(null)}>{t("Cancel editing", "取消编辑")}</button></div>
    </form>}
    <div style={rowStyle}>
      <select aria-label={t("Model to test", "待测试模型")} value={modelId} disabled={busy || !!draft || !modelsReady} onChange={event => { setModelId(event.target.value); setResult(null); }} style={input}>
        <option value="">{t("Select registered model", "选择已注册模型")}</option>
        {modelGroups.filter(group => group.values.length).map(group => <optgroup key={group.label} label={group.label}>{group.values.map(model => <option key={model.model_id} value={model.model_id}>{model.display_name} · {model.model_id}</option>)}</optgroup>)}
      </select>
      <button disabled={busy || !!draft || !modelsReady || !models.some(model => model.model_id === modelId)} onClick={test} style={btnSecondary}>{t("Run inference test", "运行推理测试")}</button>
      <small>{t("An explicit model request; Provider charges may apply.", "将提交实际模型请求，服务商可能收费。")}</small>
    </div>
    {result && <section aria-label={t("Model test result", "模型测试结果")}>
      <strong>{result.healthy ? t("Inference completed", "推理已完成") : t("Inference failed / blocked", "推理失败或受阻")}</strong>
      <p>{t("Tested model", "已测试模型")}: <code>{result.model_id}</code></p>
      {result.error && <p role="alert">{result.error}</p>}
      <p>Tokens: {measured(result.tokens_used)} · USD: {["reported", "derived", "estimated"].includes(result.cost_measurement || "") ? measured(result.cost_usd) : "UNKNOWN"} · {result.cost_measurement || "unknown"}</p>
      <details><summary>{t("Original request", "原始请求")}</summary><p>{result.request_id || "UNKNOWN"}</p><p>{result.response_preview}</p><p>{result.execution?.path || "UNKNOWN"} · {result.execution?.operation_id || result.execution?.workload_id || "UNKNOWN"}</p></details>
    </section>}
  </section>;
}
