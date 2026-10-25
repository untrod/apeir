import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, captureRuntimeConnection, governedStudioMutation } from "../../lib/api";
import type { StudioUIReview } from "../../lib/studioExtensions";
import type { PanelProps } from "./StudioPanels";
import { useStudioSnapshot } from "./StudioData";

/** Existing ExtensionRegistry review/install/lifecycle, with no executable UI loading. */
export function StudioExtensions({ locale, isVisible, onDraftChange, onDraftSnapshot }: PanelProps) {
  const { extensions, invalidateExtensions, refresh, subscribeLive } = useStudioSnapshot();
  const [guard] = useState(captureRuntimeConnection), alive = useRef(true);
  const [source, setSource] = useState(""), [review, setReview] = useState<StudioUIReview | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [uncertain, setUncertain] = useState(false);
  const input = useRef<HTMLInputElement>(null), operation = useRef(false);
  const active = useCallback(() => isVisible() && document.visibilityState !== "hidden", [isVisible]);
  useEffect(() => subscribeLive(active, ["extensions"]), [active, subscribeLive]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onDraftChange(!!source || busy || uncertain); onDraftSnapshot(source ? [{ path: "extension-review.json", content: source, originalSha256: "" }] : []); }, [source, busy, uncertain, onDraftChange, onDraftSnapshot]);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const check = () => { guard(); if (!alive.current) throw new Error("Controller presentation retired"); };
  const mutate = async (action: "install" | "configure" | "remove", body: Record<string, unknown>) => {
    if (operation.current || uncertain) return;
    operation.current = true; setBusy(true); setMessage("");
    try {
      await governedStudioMutation(`/api/v1/studio/extensions/${action}`, body, check);
      check(); invalidateExtensions(); setMessage(t("Saved", "已保存"));
      if (action === "install") { setSource(""); setReview(null); }
    } catch (error) {
      try {
        check(); setMessage(error instanceof ApiError ? `${error.code} · ${error.message} · ${JSON.stringify(error.details || {})}` : String(error));
        // A lost response is reconciled by reading the Registry, never an automatic retry.
        if (!(error instanceof ApiError) || !["NOUS_APPROVAL_REQUIRED", "NOUS_FORBIDDEN", "NOUS_INVALID_REQUEST", "NOUS_NOT_AVAILABLE"].includes(error.code)) { setUncertain(true); invalidateExtensions(); }
      } catch { /* Original request and effects remain managed by Runtime. */ }
    } finally { operation.current = false; if (alive.current) setBusy(false); }
  };
  return <section className="studio-extensions studio-projection" aria-label="UI Extensions">
    <header><strong>{t("UI Extensions", "界面扩展")}</strong><button disabled={busy} onClick={() => refresh(["extensions"])}>{t("Refresh", "刷新")}</button><button disabled={busy} onClick={() => input.current?.click()}>{t("Review manifest", "审查清单")}</button></header>
    <input type="file" hidden ref={input} accept="application/json,.json" aria-label="Import UI extension" onChange={async event => {
      const file = event.target.files?.[0]; event.target.value = ""; if (!file || operation.current || uncertain) return;
      operation.current = true; setBusy(true); setMessage(""); setReview(null);
      try {
        check(); if (file.size > 128 * 1024) throw new Error("Manifest exceeds 128 KiB");
        const text = await file.text(); check(); setSource(text);
        const result = await api<StudioUIReview>("/api/v1/studio/extensions/review", { method: "POST", body: JSON.stringify({ source_manifest: text }) });
        check(); if (!result || typeof result.digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(result.digest)) throw new Error("Invalid reviewed package digest"); setReview(result);
      } catch (error) { try { check(); setMessage(String(error)); } catch { /* Retired Controller. */ } }
      finally { operation.current = false; if (alive.current) setBusy(false); }
    }} />
    {message && <p role="status" className="studio-extension-message">{message}</p>}
    {uncertain && <div role="alert">UNKNOWN · {t("Refresh and inspect the original package state before continuing. No operation was retried.", "请刷新并核对原始包状态后继续，未重试操作。")}<button onClick={() => { setUncertain(false); setMessage(""); }}>{t("I inspected the original state", "已核对原始状态")}</button></div>}
    {source && <article className="studio-extension-review"><h3>{review?.extension_id || t("Manifest review", "清单审查")}</h3>{review && <><dl><dt>{t("Version", "版本")}</dt><dd>{review.version}</dd><dt>SHA-256</dt><dd>{review.digest}</dd><dt>{t("Publisher", "发布者")}</dt><dd>UNVERIFIED</dd></dl><details><summary>{t("Permissions & contributions", "请求权限与组件")}</summary><pre>{JSON.stringify(review.manifest, null, 2)}</pre></details><button disabled={busy || uncertain} onClick={() => void mutate("install", { source_manifest: source, expected_digest: review.digest, expected_previous_digest: review.previous_digest })}>{t("Request install", "请求安装")}</button></>}<button disabled={busy} onClick={() => { setSource(""); setReview(null); }}>{t("Discard review", "放弃审查")}</button></article>}
    {extensions.error ? <p role="alert">UNAVAILABLE · {extensions.error}</p> : !extensions.data && extensions.loading ? <p role="status">LOADING</p> : <>{!extensions.data?.extensions.length && <p role="status">{t("No UI extensions installed", "尚未安装界面扩展")}</p>}{extensions.data?.extensions.map(record => <article className="studio-extension-record" key={record.extension_id}><div className="studio-row-heading"><strong>{record.extension_id}</strong><span className="studio-status studio-status-neutral">{record.enabled ? "ENABLED" : "DISABLED"}</span></div><small>{record.version} · {record.publisher_trust} · {record.authority}</small><details><summary>{t("Package details", "包详情")}</summary><p>{record.digest}</p><p>{record.signature_status}</p><p>{record.contributions.map(item => item.title).join(" · ")}</p></details><button disabled={busy || uncertain || record.state === "revoked"} onClick={() => void mutate("configure", { extension_id: record.extension_id, enabled: !record.enabled, expected_digest: record.digest, expected_version: record.version })}>{record.enabled ? t("Disable", "禁用") : t("Enable", "启用")}</button><button disabled={busy || uncertain} onClick={() => { if (window.confirm(t(`Remove ${record.extension_id}? Existing layout slots will remain.`, `卸载 ${record.extension_id}？现有布局槽位将保留。`))) void mutate("remove", { extension_id: record.extension_id, expected_digest: record.digest, expected_version: record.version }); }}>{t("Remove", "卸载")}</button></article>)}{extensions.data?.diagnostics.map((item, i) => <p role="alert" key={i}>{item.state} · {item.extension_id} · {item.reason}</p>)}</>}
    <details className="studio-card-details"><summary>{t("Compatibility", "兼容性")}</summary>apeir.studio-ui/v1 · {t("Declarative UI only. Executable JavaScript UI: BLOCKED. Installation and display do not grant tool permissions.", "仅声明式界面。可执行 JavaScript 界面：BLOCKED。安装与展示不授予工具权限。")}</details>
  </section>;
}
