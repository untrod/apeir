import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, captureRuntimeConnection, governedStudioMutation } from "../../lib/api";
import type { StudioUIReview } from "../../lib/studioExtensions";
import type { PanelProps } from "./StudioPanels";
import { useStudioSnapshot } from "./StudioData";

type Props = PanelProps & { kind: "ui" | "tools"; mode: "installed" | "discover"; query: string; onInstalled: () => void };
const uncertainError = (error: unknown) => !(error instanceof ApiError) || !["NOUS_APPROVAL_REQUIRED", "NOUS_FORBIDDEN", "NOUS_INVALID_REQUEST", "NOUS_NOT_AVAILABLE", "NOUS_UNAUTHENTICATED", "NOUS_HUMAN_APPROVAL_REQUIRED"].includes(error.code);

/** One package review/lifecycle view over the original Registry and Governance. */
export function StudioPackages({ kind, mode, query, locale, isVisible, onDraftChange, onDraftSnapshot, open, onInstalled }: Props) {
  const { extensions, invalidateExtensions, subscribeLive } = useStudioSnapshot();
  const [guard] = useState(captureRuntimeConnection), alive = useRef(true), operation = useRef(false);
  const [source, setSource] = useState(""), [review, setReview] = useState<StudioUIReview | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [uncertain, setUncertain] = useState(false);
  const [imported, setImported] = useState(false), [errorDetails, setErrorDetails] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const active = useCallback(() => isVisible() && document.visibilityState !== "hidden", [isVisible]);
  useEffect(() => subscribeLive(active, ["extensions"]), [active, subscribeLive]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onDraftChange(imported || busy || uncertain); onDraftSnapshot(source ? [{ path: `${kind}-extension-review.json`, content: source, originalSha256: "" }] : []); }, [source, imported, busy, uncertain, kind, onDraftChange, onDraftSnapshot]);
  const check = () => { guard(); if (!alive.current) throw new Error("Controller presentation retired"); };
  const base = `/api/v1/studio/extensions${kind === "tools" ? "/tools" : ""}`;
  const mutate = async (action: "install" | "configure" | "remove", body: Record<string, unknown>) => {
    if (operation.current || uncertain) return;
    operation.current = true; setBusy(true); setMessage(""); setErrorDetails(null);
    try {
      await governedStudioMutation(`${base}/${action}`, body, check);
      check(); invalidateExtensions(); setMessage(t("Saved", "已保存"));
      if (action === "install") { setSource(""); setReview(null); setImported(false); onInstalled(); }
    } catch (error) {
      try { check(); setMessage(error instanceof ApiError ? `${error.code} · ${error.message}` : String(error)); setErrorDetails(error instanceof ApiError ? error.details : null); if (uncertainError(error)) { setUncertain(true); invalidateExtensions(); } } catch { /* Retired Controller. */ }
    } finally { operation.current = false; if (alive.current) setBusy(false); }
  };
  const tools = extensions.data?.tool_extensions;
  const records = kind === "ui" ? extensions.data?.extensions : tools?.records;
  const filtered = records?.filter(row => `${row.extension_id} ${"contributions" in row ? row.contributions.map(item => item.title).join(" ") : row.tools.map(item => item.name).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="studio-extension-group" aria-label={kind === "ui" ? "UI Extensions" : "Tool Extensions"}>
    <header><h3>{kind === "ui" ? t("Interface widgets", "界面组件") : t("MCP & API tools", "MCP 与 API 工具")}</h3>{mode === "discover" && <button disabled={busy || uncertain} onClick={() => input.current?.click()}>{kind === "ui" ? t("Import UI manifest", "导入界面清单") : t("Import tool configuration", "导入工具配置")}</button>}</header>
    <input type="file" hidden ref={input} accept="application/json,.json" aria-label={kind === "ui" ? "Import UI extension" : "Import tool extension"} onChange={async event => {
      const file = event.target.files?.[0]; event.target.value = ""; if (!file || operation.current || uncertain) return;
      operation.current = true; setBusy(true); setMessage(""); setErrorDetails(null); setReview(null); setSource(""); setImported(true);
      try {
        check(); if (file.size > 128 * 1024) throw new Error(t("Manifest exceeds 128 KiB", "清单不能超过 128 KiB"));
        const text = await file.text(); check();
        const result = await api<StudioUIReview>(`${base}/review`, { method: "POST", body: JSON.stringify({ source_manifest: text }) });
        check(); if (!result || typeof result.digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(result.digest)) throw new Error("Invalid reviewed package digest"); setReview(result); setSource(text);
      } catch (error) { try { check(); setMessage(String(error)); } catch { /* Retired Controller. */ } }
      finally { operation.current = false; if (alive.current) setBusy(false); }
    }} />
    {busy && <p role="status">{t("Working…", "正在处理…")}</p>}
    {message && <div role="status">{message}{!!errorDetails && <details><summary>{t("Request details", "请求详情")}</summary><pre>{JSON.stringify(errorDetails)}</pre></details>}</div>}
    {uncertain && <div role="alert">{t("Outcome unconfirmed. Refresh and inspect the original package before continuing.", "结果尚未确认。请刷新并核对原始包状态后继续。")}<button onClick={() => { setUncertain(false); setMessage(""); }}>{t("I inspected the original state", "已核对原始状态")}</button></div>}
    {imported && <article className="studio-extension-record"><h4>{review?.extension_id || t("Package review", "安装确认")}</h4>{review && <><p>{review.version} · {t("Unverified publisher", "发布者身份未验证")}</p><details><summary>{t("Source, permissions & compatibility", "来源、权限与兼容性")}</summary><p>{review.digest}</p><pre>{JSON.stringify(review.manifest, null, 2)}</pre></details><button disabled={busy || uncertain} onClick={() => void mutate("install", { source_manifest: source, expected_digest: review.digest, expected_previous_digest: review.previous_digest })}>{t("Request install", "请求安装")}</button><button onClick={() => open("operations")}>{t("Approvals", "查看审批")}</button></>}<button disabled={busy} onClick={() => { setSource(""); setReview(null); setImported(false); }}>{t("Cancel", "取消")}</button></article>}
    {extensions.error ? <p role="alert">{t("Unavailable", "暂不可用")} · {extensions.error}</p> : !extensions.data ? <p role="status">{extensions.loading ? t("Loading…", "正在加载…") : t("Runtime data unavailable", "无法读取 Runtime 数据")}</p> : mode === "installed" && <>
      {kind === "tools" && !tools && <p role="status">{t("This Runtime does not expose tool extension management.", "当前 Runtime 未提供工具扩展管理接口。")}</p>}
      {filtered?.length === 0 && <p className="studio-extension-empty">{query ? t("No matching extensions", "没有匹配的扩展") : t("Nothing installed here yet", "这里还没有已安装的扩展")}</p>}
      {filtered?.map(row => <article className="studio-extension-record" key={row.extension_id}><div className="studio-row-heading"><h4>{row.extension_id}</h4><span className="studio-status studio-status-neutral">{kind === "tools" ? row.enabled ? t("Enabled for tasks", "任务中启用") : t("Disabled for tasks", "任务中禁用") : row.enabled ? t("Enabled", "已启用") : t("Disabled", "已禁用")}</span></div><small>{row.version} · {kind === "ui" ? t("Interface", "界面") : t("Tool", "工具")}</small>
        {"status" in row && row.status !== "DISABLED" && <p role="status">{({ REVOKED: t("Revoked", "已撤销"), NEEDS_AUTHORIZATION: t("Kernel authorization required", "待 Kernel 授权"), NEEDS_DISCOVERY: t("Tool discovery required", "待发现工具"), UNSUPPORTED: t("Unsupported executor", "执行器不受支持"), KERNEL_CHECK_REQUIRED: t("Kernel checks every call; availability depends on its executor", "每次调用均须 Kernel 检查，可用性取决于执行器") })[row.status]}</p>}
        <details><summary>{t("Details", "详情")}</summary><p>{row.digest}</p><p>{row.authority}</p>{"contributions" in row ? <p>{row.contributions.map(item => item.title).join(" · ")}</p> : <><p>{row.tools.map(item => `${item.name} (${item.protocol})`).join(" · ") || t("No discovered tools", "尚无已发现工具")}</p><p>{t("Kernel admission, capability approval and MCP discovery use the existing Extension CLI. Enabling here does not supply them.", "Kernel 准入、能力审批及 MCP 发现使用现有 Extension CLI；此处启用不会代办授权。")}</p></>}</details>
        <div className="studio-extension-actions"><button disabled={busy || uncertain || row.state === "revoked"} onClick={() => void mutate("configure", { extension_id: row.extension_id, enabled: !row.enabled, expected_digest: row.digest, expected_version: row.version })}>{kind === "tools" ? row.enabled ? t("Disable for tasks", "从任务中禁用") : t("Enable for tasks", "在任务中启用") : row.enabled ? t("Disable", "禁用") : t("Enable", "启用")}</button><button disabled={busy || uncertain || row.state === "revoked"} onClick={() => { if (window.confirm(t(`Uninstall ${row.extension_id}? Recorded evidence is retained.`, `卸载 ${row.extension_id}？历史证据将保留。`))) void mutate("remove", { extension_id: row.extension_id, expected_digest: row.digest, expected_version: row.version }); }}>{t("Uninstall", "卸载")}</button></div>
      </article>)}
      {(kind === "ui" ? extensions.data.diagnostics : tools?.diagnostics)?.map((item, i) => <p role="alert" key={i}>{item.state} · {item.extension_id} · {item.reason}</p>)}
    </>}
    {mode === "discover" && <p className="studio-extension-empty">{kind === "ui" ? t("Import a declarative widget manifest. Custom JavaScript remains blocked.", "导入声明式组件清单。第三方 JavaScript 尚未开放。") : t("Import an MCP configuration or OpenAPI JSON document. Install first, then configure and authorize its tools.", "导入 MCP 配置或 OpenAPI JSON 文档，安装后再配置并授权工具。")}</p>}
  </section>;
}
