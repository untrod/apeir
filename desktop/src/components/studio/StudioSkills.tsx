import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, captureRuntimeConnection, humanMutation } from "../../lib/api";
import type { PanelProps } from "./StudioPanels";
import { useStudioSnapshot } from "./StudioData";

type Row = Record<string, unknown>;
type Props = PanelProps & { mode: "installed" | "discover"; query: string; onInstalled: () => void };
const value = (row: Row, key: string) => typeof row[key] === "string" ? row[key] as string : "";
const items = (row: Row, key: string) => Array.isArray(row[key]) ? (row[key] as unknown[]).filter(item => typeof item === "string").join(" · ") : "";

export function StudioSkills({ mode, query, locale, isVisible, onDraftChange, onDraftSnapshot, open, onInstalled }: Props) {
  const { data, error, loading, invalidateOperations, subscribeLive } = useStudioSnapshot();
  const [guard] = useState(captureRuntimeConnection), alive = useRef(true), operation = useRef(false);
  const [review, setReview] = useState<Row | null>(null), [source, setSource] = useState("");
  const [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false), [message, setMessage] = useState("");
  const [instructions, setInstructions] = useState("");
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const active = useCallback(() => isVisible() && document.visibilityState !== "hidden", [isVisible]);
  useEffect(() => subscribeLive(active, ["operations"]), [active, subscribeLive]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onDraftChange(!!review || busy || uncertain || !!source); onDraftSnapshot([]); }, [review, busy, uncertain, source, onDraftChange, onDraftSnapshot]);
  const check = () => { guard(); if (!alive.current) throw new Error("Controller presentation retired"); };
  const act = async (action: string, row: Row) => {
    if (operation.current || uncertain) return;
    operation.current = true; setBusy(true); setMessage(""); setInstructions("");
    const catalog = action.startsWith("catalog_");
    const body = catalog ? { kind: "skills", action, target_id: value(row, "source"), catalog_source: value(row, "source") } : {
      kind: "skills", action, target_id: value(row, "skill_key"), version: value(row, "version"), digest: value(row, "digest"), catalog_source: value(row, "catalog_source"), package_source: value(row, "package_source"),
    };
    try {
      const result = await humanMutation<{ skill?: { skill?: { instructions?: string } } }>("/api/v1/control/operations/actions", body, check);
      check(); invalidateOperations(); setMessage(t("Saved", "已保存")); setReview(null);
      if (catalog) setSource("");
      if (action === "install") onInstalled();
      if (action === "load") setInstructions(result.skill?.skill?.instructions || "");
    } catch (error) {
      try {
        check(); setMessage(error instanceof ApiError ? `${error.code} · ${error.message}` : String(error));
        if (!(error instanceof ApiError) || !["NOUS_FORBIDDEN", "NOUS_UNAUTHENTICATED", "NOUS_INVALID_REQUEST", "NOUS_HUMAN_APPROVAL_REQUIRED", "NOUS_APPROVAL_REQUIRED"].includes(error.code)) { setUncertain(true); invalidateOperations(); }
      } catch { /* Retired Controller. */ }
    } finally { operation.current = false; if (alive.current) setBusy(false); }
  };
  const rows = data?.skills?.filter(row => (mode === "discover" ? row.provider === "catalog" : row.provider !== "catalog") && `${value(row, "name")} ${value(row, "description")} ${items(row, "tags")}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="studio-extension-group" aria-label="Skills">
    <header><h3>{t("Skills", "技能")}</h3></header>
    {busy && <p role="status">{t("Working…", "正在处理…")}</p>}
    {message && <p role="status">{message}</p>}
    {uncertain && <div role="alert">{t("Outcome unconfirmed. Refresh and inspect the original installation before continuing.", "结果尚未确认。请刷新并核对原始安装状态后继续。")}<button onClick={() => { setUncertain(false); setMessage(""); }}>{t("I inspected the original state", "已核对原始状态")}</button></div>}
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">{loading ? t("Loading…", "正在加载…") : t("Runtime unavailable", "Runtime 暂不可用")}</p> : !rows ? <p role="status">{t("This Runtime does not expose Skills.", "当前 Runtime 未提供技能列表。")}</p> : <>
      {rows.length === 0 && <p className="studio-extension-empty">{query ? t("No matching Skills", "没有匹配的技能") : mode === "discover" ? t("Add a catalog to discover reviewed Skill packages.", "添加目录源后，可以浏览并安装技能包。") : t("No Skills installed", "尚未安装技能")}</p>}
      {rows.map(row => {
        const installed = data.skills?.find(item => item.provider === "installed" && item.skill_id === row.skill_id);
        const same = installed?.digest === row.digest;
        const blocked = row.identity_status === "AMBIGUOUS" || row.state === "revoked";
        return <article className="studio-extension-record" key={value(row, "skill_key")}><div className="studio-row-heading"><h4>{value(row, "name")}</h4><span className="studio-status studio-status-neutral">{mode === "discover" ? t("Skill", "技能") : row.enabled ? t("Enabled", "已启用") : t("Disabled", "已禁用")}</span></div><p>{value(row, "description")}</p><small>{value(row, "version")} · {value(row, "provider")}</small>
          <details><summary>{t("Details", "详情")}</summary><p>{value(row, "source")}</p><p>{value(row, "digest")}</p><p>{items(row, "requested_capabilities")}</p><p>{value(row, "compatibility")}</p></details>
          {blocked && <p role="status">{t("Blocked: review the original identity and revocation state.", "已阻止：请检查原始身份或撤销状态。")}</p>}
          <div className="studio-extension-actions">{mode === "discover" ? <button disabled={busy || uncertain || blocked || same || row.installable !== true} onClick={() => { setInstructions(""); setReview(row); }}>{same ? t("Installed", "已安装") : installed ? t("Review update", "更新") : t("Install", "安装")}</button> : <><button disabled={busy || uncertain || blocked} onClick={() => void act(row.enabled ? "disable" : "enable", row)}>{row.enabled ? t("Disable", "禁用") : t("Enable", "启用")}</button><button disabled={busy || uncertain || blocked || !row.enabled} onClick={() => void act("load", row)}>{t("Read instructions", "查看说明")}</button>{row.provider === "installed" && <button disabled={busy || uncertain || blocked} onClick={() => { if (window.confirm(t(`Uninstall ${value(row, "name")}?`, `卸载 ${value(row, "name")}？`))) void act("remove", row); }}>{t("Uninstall", "卸载")}</button>}</>}</div>
        </article>;
      })}
      {data.skill_diagnostics?.map((item, i) => <p role="alert" key={i}>{value(item, "source")} · {value(item, "error")}</p>)}
    </>}
    {review && <article className="studio-extension-review" aria-label="Review Skill installation"><h4>{value(review, "name")}</h4><p>{value(review, "version")} · {t("Unverified publisher", "发布者身份未验证")}</p><p>{value(review, "package_source")}</p><p>{t("This package supplies instructions. Tool operations still require authorization.", "此包提供技能说明，工具操作仍需独立授权。")}</p><details><summary>{t("Permissions & integrity", "权限与完整性")}</summary><p>{items(review, "requested_capabilities")}</p><p>{value(review, "risk")} · {value(review, "digest")}</p></details><button disabled={busy || uncertain} onClick={() => void act("install", review)}>{t("Install reviewed package", "确认安装")}</button><button disabled={busy} onClick={() => setReview(null)}>{t("Cancel", "取消")}</button></article>}
    {instructions && <details open><summary>{t("Loaded instructions", "已加载的技能说明")}</summary><pre>{instructions}</pre></details>}
    {mode === "discover" && <details className="studio-card-details"><summary>{t("Catalog sources", "目录源")}</summary><form onSubmit={event => {
      event.preventDefault();
      try { const url = new URL(source); if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) throw new Error(); }
      catch { setMessage(t("Use an HTTPS catalog URL without credentials or query parameters.", "请使用不含凭据或查询参数的 HTTPS 目录地址。")); return; }
      if (window.confirm(t(`Add and download this catalog?\n${source}`, `添加并下载此目录？\n${source}`))) void act("catalog_add", { source });
    }}><label>{t("Catalog URL", "目录地址")}<input type="url" value={source} onChange={event => setSource(event.target.value)} placeholder="https://example.org/skills/catalog.json" /></label><button disabled={busy || uncertain || !source}>{t("Add source", "添加源")}</button></form>{data?.skill_catalogs?.map(row => <div className="studio-extension-catalog" key={value(row, "source")}><span>{value(row, "source")}</span><button disabled={busy || uncertain} onClick={() => { if (window.confirm(t("Refresh this catalog over the network?", "联网刷新此目录？"))) void act("catalog_refresh", row); }}>{t("Refresh source", "刷新源")}</button><button disabled={busy || uncertain} onClick={() => { if (window.confirm(t("Remove this catalog source? Installed Skills remain.", "移除此目录源？已安装技能将保留。"))) void act("catalog_remove", row); }}>{t("Remove source", "移除源")}</button></div>)}</details>}
    <details className="studio-card-details"><summary>{t("Permissions", "权限")}</summary><p>{t("Installation requires a current human session and the workspace owner's permissions for the exact package source.", "安装需要当前用户会话，以及工作区所有者对该包来源的授权。")}</p><button onClick={() => open("operations")}>{t("Open access & approvals", "打开访问与审批")}</button></details>
  </section>;
}
