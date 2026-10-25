import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, captureRuntimeConnection, governedStudioMutation } from "../../lib/api";
import type { StudioUIContribution, StudioUIExtension, StudioUIView, StudioView } from "../../lib/studioExtensions";
import { useStudioSnapshot } from "./StudioData";

const display = (value: unknown) => value === null || value === undefined || value === "" ? "UNKNOWN" : String(value);
/** Trusted React rendering of strictly validated data. No dynamic code, HTML or URLs. */
function View({ view, status, record, contribution, locale }: { locale: "en" | "zh"; view: StudioView; status: StudioUIView["status"]; record: StudioUIExtension; contribution: StudioUIContribution }) {
  if (view.kind === "stack") return <div className="studio-extension-stack">{view.label && <strong>{view.label}</strong>}{view.children.map((child, i) => <View key={i} view={child} status={status} record={record} contribution={contribution} locale={locale} />)}</div>;
  if (view.kind === "text") return <div><small>{view.label}</small><p>{view.text}</p></div>;
  if (view.kind === "action") return <GovernedAction view={view} record={record} contribution={contribution} />;
  if (view.kind === "table") return <table><caption>{view.label}</caption><tbody>{view.fields.map((field, i) => <tr key={i}><th scope="row">{field.label}</th><td>{display(status?.[field.field])}</td></tr>)}</tbody></table>;
  const value = status?.[view.field];
  if (view.kind === "chart") return <StatusChart label={view.label || view.field} value={value} locale={locale} />;
  return <div className="studio-extension-value"><small>{view.label || view.field}</small><strong className={view.kind === "status" ? "studio-status studio-status-neutral" : "studio-metric-value"}>{view.kind === "status" && typeof value === "boolean" ? view.field === "running" ? value ? "ONLINE" : "OFFLINE" : view.field === "kernel_ready" ? value ? "READY" : "NOT_READY" : String(value) : display(value)}</strong></div>;
}
function StatusChart({ label, value, locale }: { label: string; value: unknown; locale: "en" | "zh" }) {
  const { extensions } = useStudioSnapshot();
  const samples = useRef<{ at: number; value: number | null }[]>([]);
  const at = extensions.receivedAt;
  if (at && samples.current.at(-1)?.at !== at) samples.current = [...samples.current, { at, value: typeof value === "number" && Number.isFinite(value) ? value : null }].slice(-24);
  const values = samples.current.filter((item): item is { at: number; value: number } => item.value !== null), max = Math.max(1, ...values.map(item => item.value)), min = Math.min(0, ...values.map(item => item.value));
  return <div className="studio-extension-chart"><small>{label}</small><strong>{typeof value === "number" && Number.isFinite(value) ? value : "UNKNOWN"}</strong>{values.length > 1 && <svg viewBox="0 0 240 48" role="img" aria-label={`${label} · ${values.length} ${locale === "zh" ? "个观测样本" : "observed samples"}`} preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" strokeWidth="2" points={values.map((item, i) => `${i / Math.max(1, values.length - 1) * 240},${46 - (item.value - min) / Math.max(1, max - min) * 42}`).join(" ")} /></svg>}<small>{values.length} {locale === "zh" ? "个样本 · 当前会话" : `${values.length === 1 ? "sample" : "samples"} · current session`}</small></div>;
}
function GovernedAction({ view, record, contribution }: { view: Extract<StudioView, {kind: "action"}>; record: StudioUIExtension; contribution: StudioUIContribution }) {
  const [guard] = useState(captureRuntimeConnection), [key] = useState(() => crypto.randomUUID());
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [busy, setBusy] = useState(false), [result, setResult] = useState(""), [retry, setRetry] = useState(true);
  const check = () => { guard(); if (!alive.current) throw new Error("Presentation retired; inspect original Runtime history"); };
  return <div><button disabled={busy || !retry} onClick={async () => {
    setBusy(true); setResult(""); setRetry(false);
    try { const original = await governedStudioMutation<{ run_id: string; state: string }>("/api/v1/studio/extensions/action", { component_type: contribution.type, expected_digest: record.digest, action: view.action, idempotency_key: key }, check); check(); setResult(`${original.run_id} · ${original.state}`); }
    catch (error) { try { check(); setResult(error instanceof ApiError ? `${error.code} · ${error.message} · ${JSON.stringify(error.details || {})}` : String(error)); setRetry(error instanceof ApiError && error.code === "NOUS_APPROVAL_REQUIRED"); } catch { /* Original request remains managed by Runtime. */ } }
    finally { if (alive.current) setBusy(false); }
  }}>{busy ? "RUNNING" : view.label}</button><output>{result}</output></div>;
}
export function StudioExtensionView({ type, isVisible, locale = "en" }: { type: string; isVisible: () => boolean; locale?: "en" | "zh" }) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const { extensions, subscribeLive } = useStudioSnapshot();
  const active = useCallback(() => isVisible() && document.visibilityState !== "hidden", [isVisible]);
  useEffect(() => subscribeLive(active, ["extensions"]), [active, subscribeLive]);
  const found = extensions.data?.extensions.flatMap(record => record.contributions.map(contribution => ({ record, contribution }))).find(item => item.contribution.type === type);
  const [events, setEvents] = useState<unknown>(null), [error, setError] = useState("");
  const [guard] = useState(captureRuntimeConnection), eventEpoch = useRef(0);
  useEffect(() => { eventEpoch.current += 1; setEvents(null); setError(""); return () => { eventEpoch.current += 1; }; }, [found?.record.digest, found?.record.enabled]);
  if (extensions.error) return <section role="status">UNAVAILABLE · {extensions.error}</section>;
  if (!extensions.data && extensions.loading) return <section role="status">LOADING</section>;
  if (!found) return <section role="status">{t("Missing Extension", "缺失扩展")}<p>{type}</p></section>;
  if (!found.record.enabled) return <section role="status">{t("DISABLED", "已禁用")}<p>{found.contribution.title}</p></section>;
  return <section className="studio-extension-view" aria-label={found.contribution.title}><View key={found.record.digest} view={found.contribution.view} status={found.contribution.subscriptions?.includes("runtime.status") ? extensions.data?.status || null : null} record={found.record} contribution={found.contribution} locale={locale} />
    {!!found.contribution.events?.length && <details><summary>{t("Lifecycle events", "生命周期事件")}</summary><button onClick={async () => { const captured = eventEpoch.current; try { guard(); const value = await api(`/api/v1/studio/extensions/events?component_type=${encodeURIComponent(type)}&expected_digest=${encodeURIComponent(found.record.digest)}`); guard(); if (eventEpoch.current === captured) setEvents(value); } catch (error) { if (eventEpoch.current === captured) setError(String(error)); } }}>{t("Read allowed events", "读取已声明事件")}</button>{error ? <p role="alert">{error}</p> : events !== null && <pre>{JSON.stringify(events, null, 2)}</pre>}</details>}
    <details className="studio-card-details"><summary>{t("Source", "来源")}</summary><p>{found.record.extension_id} · {found.record.version}</p><p>{found.record.digest}</p><p>runtime-service · NOT_PHYSICAL_VERIFICATION · publisher {found.record.publisher_trust}</p></details>
  </section>;
}
