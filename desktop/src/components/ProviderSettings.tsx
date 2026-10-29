import { useCallback, useEffect, useRef, useState } from "react";
import { btnPrimary, btnSecondary, colors, input, space } from "../design";
import { ApiError, api, getRuntimeConfigVersion, governedStudioMutation, testModel, type ModelLabSnapshot, type ModelTestResult } from "../lib/api";
import { useRuntimeConfigVersion } from "../store";
import { PROVIDER_TEMPLATES } from "./OnboardingWizard";

type SavedConfiguration = { name: string; api_base_url: string; model: string; has_reference: boolean };
type ProviderSummary = { id: string; name: string; health?: { status?: string }; configuration?: SavedConfiguration };
type Draft = { id: string; name: string; endpoint: string; model: string; credential: string; clearCredential: boolean; original?: SavedConfiguration };

/** Presentation over the existing Provider lifecycle; credentials remain references. */
export function ProviderSettings({ locale = "en", models, onChanged, onOpenApprovals }: {
  locale?: "en" | "zh"; models: ModelLabSnapshot["models"]; onChanged: () => Promise<void>; onOpenApprovals?: () => void;
}) {
  const version = useRuntimeConfigVersion();
  const active = useRef(false), inFlight = useRef(false), reads = useRef(0);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [message, setMessage] = useState(""), [removing, setRemoving] = useState("");
  const [templateId, setTemplateId] = useState("openai");
  const [modelId, setModelId] = useState("");
  const [result, setResult] = useState<ModelTestResult | null>(null);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const current = useCallback(() => {
    if (!active.current || getRuntimeConfigVersion() !== version) throw new Error("Controller changed; review the original request.");
  }, [version]);
  const refresh = useCallback(async () => {
    const sequence = ++reads.current;
    current(); setProviders([]);
    const rows = await api<ProviderSummary[]>("/api/v1/providers");
    current();
    if (!Array.isArray(rows) || rows.some(row => !row || typeof row.id !== "string" || typeof row.name !== "string" || row.configuration && (
      typeof row.configuration !== "object" || [row.configuration.name, row.configuration.api_base_url, row.configuration.model].some(value => typeof value !== "string") || typeof row.configuration.has_reference !== "boolean"
    )) || new Set(rows.map(row => row.id)).size !== rows.length) {
      throw new Error("Provider metadata is unavailable.");
    }
    if (sequence === reads.current) setProviders(rows);
  }, [current]);
  useEffect(() => {
    active.current = true;
    inFlight.current = false; setBusy(false); setDraft(null); setResult(null); setModelId(""); setRemoving(""); setError(""); setMessage(""); setApprovalRequired(false);
    void refresh().catch(() => { if (active.current && getRuntimeConfigVersion() === version) setError("Provider metadata is unavailable."); });
    return () => { active.current = false; };
  }, [refresh, version]);

  const perform = async (action: () => Promise<void>) => {
    if (inFlight.current) return;
    current(); inFlight.current = true; setBusy(true); setError(""); setMessage(""); setApprovalRequired(false);
    try { await action(); }
    catch (cause) {
      if (active.current && getRuntimeConfigVersion() === version) {
        setError(cause instanceof Error ? cause.message : "Request failed; inspect original state before retrying.");
        setApprovalRequired(cause instanceof ApiError && cause.code.includes("APPROVAL_REQUIRED"));
      }
    } finally {
      if (active.current && getRuntimeConfigVersion() === version) { inFlight.current = false; setBusy(false); }
    }
  };
  const newDraft = (id: string) => {
    const preset = PROVIDER_TEMPLATES.find(item => item.providerId === id);
    setTemplateId(id); setDraft({ id, name: preset?.displayName || "", endpoint: preset?.defaultBaseUrl || "", model: "", credential: "", clearCredential: false });
    setRemoving(""); setError(""); setMessage("");
  };
  const save = async () => {
    if (!draft) return;
    const originalDraft = draft;
    await perform(async () => {
      if (!/^[A-Za-z0-9._-]+$/.test(draft.id) || !draft.name.trim() || !draft.endpoint.trim() || !draft.model.trim()) throw new Error(t("Complete Provider ID, name, endpoint and model ID.", "请填写服务商 ID、名称、端点和模型 ID。"));
      if (draft.credential && !/^env:[A-Z_][A-Z0-9_]{0,127}$/.test(draft.credential)) throw new Error(t("Enter an env:NAME reference, never an API key.", "请输入 env:NAME 凭据引用，不要粘贴 API Key。"));
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
    if (removing !== id) { setRemoving(id); return; }
    void perform(async () => {
      await governedStudioMutation(`/api/v1/providers/${encodeURIComponent(id)}`, {}, current, "DELETE");
      current(); setRemoving(""); setDraft(null);
      setMessage(t("Provider removed. Its credential and admitted requests are unchanged.", "服务商已移除；独立凭据及已接纳的请求不受影响。"));
      await refresh(); current(); await onChanged();
    });
  };
  const test = () => void perform(async () => {
    if (!models.some(model => model.model_id === modelId)) throw new Error("Select a currently registered model.");
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
  return <section aria-label={t("Provider settings", "服务商设置")} style={{ display: "grid", gap: space.sm, marginBottom: space.lg }}>
    <div style={rowStyle}><strong>{t("Providers", "服务商")}</strong>
      <button style={btnSecondary} disabled={busy || !!draft} onClick={() => newDraft("openai")}>{t("Add Provider", "添加服务商")}</button>
      <button style={btnSecondary} disabled={busy} onClick={() => void perform(refresh)}>{t("Refresh Providers", "刷新服务商")}</button>
    </div>
    {error && <p role="alert" style={{ color: colors.danger }}>{error}</p>}
    {approvalRequired && onOpenApprovals && <button style={{ ...btnSecondary, justifySelf: "start" }} onClick={onOpenApprovals}>{t("Open original approvals", "查看原始审批")}</button>}
    {message && <p role="status">{message}</p>}
    {!providers.length && <p>{t("No registered or saved Providers reported.", "尚未发现已注册或已保存的服务商。")}</p>}
    {providers.map(provider => <div key={provider.id} style={rowStyle}>
      <span style={{ flex: 1 }}>{provider.name} <code>{provider.id}</code> · {typeof provider.health?.status === "string" ? provider.health.status : "UNKNOWN"}</span>
      <button style={btnSecondary} disabled={busy || !provider.configuration || !!draft} aria-label={`${t("Edit", "编辑")} ${provider.id}`} onClick={() => {
        const config = provider.configuration!;
        setDraft({ id: provider.id, name: config.name, endpoint: config.api_base_url, model: config.model, credential: "", clearCredential: false, original: config }); setRemoving(""); setMessage("");
      }}>{t("Edit", "编辑")}</button>
      <button style={btnSecondary} disabled={busy || !provider.configuration} aria-label={`${removing === provider.id ? t("Confirm remove", "确认移除") : t("Remove", "移除")} ${provider.id}`} onClick={() => remove(provider.id)}>{removing === provider.id ? t("Confirm remove", "确认移除") : t("Remove", "移除")}</button>
      {provider.configuration && <small style={{ width: "100%" }}>{provider.configuration.model || "UNKNOWN"} · {provider.configuration.api_base_url || "UNKNOWN"} · {provider.configuration.has_reference ? t("Reference saved", "引用已保存") : t("No saved reference", "无已保存引用")}</small>}
    </div>)}
    {draft && <form onSubmit={event => { event.preventDefault(); void save(); }} style={{ display: "grid", gap: space.sm }}>
      {!draft.original && <label>{t("Protocol template", "协议模板")} <select aria-label={t("Protocol template", "协议模板")} value={templateId} disabled={busy} onChange={event => newDraft(event.target.value)} style={input}>
        {PROVIDER_TEMPLATES.map(preset => <option key={preset.providerId} value={preset.providerId} disabled={preset.unsupportedProtocol}>{preset.displayName}{preset.unsupportedProtocol ? " · UNSUPPORTED" : ""}</option>)}
      </select></label>}
      {([["id", "Provider ID", "服务商 ID"], ["name", "Name", "名称"], ["endpoint", "Endpoint", "端点"], ["model", "Vendor model ID", "厂商模型 ID"], ["credential", "Credential reference", "凭据引用"]] as const).map(([key, en, zh]) => <label key={key}>{t(en, zh)} <input aria-label={t(en, zh)} autoComplete="off" spellCheck={false} style={input} disabled={busy || key === "id" && !!draft.original} value={draft[key]} onChange={event => setDraft(previous => previous && ({ ...previous, [key]: event.target.value }))} placeholder={key === "credential" ? draft.original ? t("Blank keeps the existing reference", "留空保留现有引用") : "env:OPENAI_API_KEY" : undefined} /></label>)}
      {draft.original && <label><input type="checkbox" checked={draft.clearCredential} disabled={busy} onChange={event => setDraft(previous => previous && ({ ...previous, clearCredential: event.target.checked }))} />{t("Clear saved credential reference", "清除已保存的凭据引用")}</label>}
      <small>{t("Store keys in Settings → Credentials or the selected host's secure backend. This form accepts references only.", "请通过设置 → 凭据或所选主机的安全后端保存密钥；此处仅接受引用。")}</small>
      <div style={rowStyle}><button type="submit" disabled={busy} style={btnPrimary}>{t("Save Provider", "保存服务商")}</button><button type="button" disabled={busy} style={btnSecondary} onClick={() => setDraft(null)}>{t("Cancel editing", "取消编辑")}</button></div>
    </form>}
    <div style={rowStyle}>
      <select aria-label={t("Model to test", "待测试模型")} value={modelId} disabled={busy} onChange={event => { setModelId(event.target.value); setResult(null); }} style={input}>
        <option value="">{t("Select registered model", "选择已注册模型")}</option>
        {models.map(model => <option key={model.model_id} value={model.model_id}>{model.display_name} · {model.model_id}</option>)}
      </select>
      <button disabled={busy || !models.some(model => model.model_id === modelId)} onClick={test} style={btnSecondary}>{t("Run inference test", "运行推理测试")}</button>
      <small>{t("An explicit model request; Provider charges may apply.", "将提交实际模型请求，服务商可能收费。")}</small>
    </div>
    {result && <section aria-label={t("Model test result", "模型测试结果")}>
      <strong>{result.healthy ? t("Inference completed", "推理已完成") : t("Inference failed / blocked", "推理失败或受阻")}</strong>
      {result.error && <p role="alert">{result.error}</p>}
      <p>Tokens: {measured(result.tokens_used)} · USD: {["reported", "derived", "estimated"].includes(result.cost_measurement || "") ? measured(result.cost_usd) : "UNKNOWN"} · {result.cost_measurement || "unknown"}</p>
      <details><summary>{t("Original request", "原始请求")}</summary><p>{result.request_id || "UNKNOWN"}</p><p>{result.response_preview}</p><p>{result.execution?.path || "UNKNOWN"} · {result.execution?.operation_id || result.execution?.workload_id || "UNKNOWN"}</p></details>
    </section>}
  </section>;
}
