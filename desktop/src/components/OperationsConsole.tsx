/** Real runtime operations; every mutation returns to the existing Governance gate. */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, getConfig, setConfig } from "../lib/api";
import { useTheme } from "../theme";
import "./OperationsConsole.css";

type Row = Record<string, unknown>;
type Collection = "agents" | "works" | "workflows" | "nodes" | "devices" | "approvals" | "grants" | "credential_leases" | "artifacts" | "evidence" | "activity" | "incidents";
export type OperationsSnapshot = Record<Collection, Row[]> & {
  health: { degraded: boolean; components: Row[] };
  controls: { actions: string[] };
};
type Human = { subject_id: string; expires_at: number };
const collections: Collection[] = ["works", "nodes", "devices", "approvals", "evidence", "incidents", "agents", "workflows", "grants", "credential_leases", "artifacts", "activity"];
const label = (value: string) => value.replaceAll("_", " ");
const text = (row: Row, keys: string[]) => String(keys.map(key => row[key]).find(value => value !== undefined && value !== null) ?? "UNKNOWN");
const rowId = (row: Row) => text(row, ["request_id", "work_id", "node_id", "device_id", "session_id", "grant_id", "lease_id", "run_id", "digest", "incident_id", "sequence"]);
const pkceKey = "apeir.human.pkce";
const record = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const refs = (value: unknown) => Array.isArray(value) && value.length ? value.map(String).join("\n") : "Not recorded";

// Only presentation preferences belong in Web Storage, never Runtime records or identity.
const layoutKey = "apeir.operations.layout.v1";
type Layout = { tabs: Collection[]; active: Collection; inspectorWidth: number; activityOpen: boolean; locale: "en" | "zh" };
const defaultLayout: Layout = { tabs: ["works"], active: "works", inspectorWidth: 380, activityOpen: false, locale: "en" };
function loadLayout(): Layout {
  try {
    const value = record(JSON.parse(localStorage.getItem(layoutKey) || "null"));
    const tabs = Array.isArray(value.tabs) ? [...new Set(value.tabs.filter((item): item is Collection => collections.includes(item as Collection)))] : ["works" as Collection];
    if (!tabs.length) tabs.push("works");
    return { tabs, active: tabs.includes(value.active as Collection) ? value.active as Collection : tabs[0], inspectorWidth: typeof value.inspectorWidth === "number" && Number.isFinite(value.inspectorWidth) ? Math.max(280, Math.min(640, value.inspectorWidth)) : 380, activityOpen: value.activityOpen === true, locale: value.locale === "zh" ? "zh" : "en" };
  } catch { return defaultLayout; }
}
const translations: Record<string, string> = {
  works: "任务", nodes: "节点", devices: "设备", approvals: "审批", evidence: "证据", incidents: "事件处置", agents: "智能体", workflows: "工作流", grants: "授权", credential_leases: "凭据租约", artifacts: "工件", activity: "活动",
  "Workspace resources": "工作区资源", "Search records": "搜索记录", "Refresh": "刷新", "Execution & reality": "执行与现实", "Observe state, inspect evidence, govern the next action.": "观察状态、检查证据、治理下一步动作。", "Sign in as human": "以用户身份登录", "Renew human session": "续期用户会话", "Sign out": "退出登录", "Controller connection": "Controller 连接", "Connect": "连接", "Close details": "关闭详情", "Evidence details": "证据详情", "Activity panel": "活动面板", "Hide activity": "收起活动", "Show activity": "展开活动", "No activity recorded.": "暂无活动记录。", "Waiting for authoritative runtime data.": "等待 Runtime 权威数据。", "No matching records.": "没有匹配的记录。", "Approve Once": "批准一次", "Deny": "拒绝", "Interrupt": "中断", "Reconcile": "核对恢复", "Resume original workflow": "恢复原工作流", "Revoke": "撤销", "Trust": "信任", "Connection": "连接状态", "Resize evidence inspector": "调整证据面板宽度", "System health": "系统健康", "Work": "任务", "Nodes": "节点", "Devices": "设备", "Pending approvals": "待审批", "Raw backend record and diagnostics": "后端原始记录与诊断", "Observe mode · human authentication required for actions": "观察模式 · 操作需要用户认证", "UNKNOWN requires reconciliation. Interrupt prevents future admission; an existing physical effect may still require observation.": "UNKNOWN 需要核对恢复。中断阻止后续准入；已经发生的物理效果仍可能需要观测。",
};

function WorkEvidence({ work }: { work: Row }) {
  const provenance = record(work.provenance);
  const receipt = record(record(work.result_summary).remote_execution_receipt);
  const verification = record(work.effect_verification);
  const fields = [
    ["Goal / intent", text(work, ["intent"])],
    ["AgentSession", text(provenance, ["agent_session_id"])],
    ["Plan", text(provenance, ["plan_id"])],
    ["Workflow", text(provenance, ["workflow_run_id"])],
    ["Authorization", text(record(work.execution_arguments), ["authorization_id"])],
    ["Operation", text(provenance, ["operation_id"])],
    ["Capability", text(work, ["execution_capability"])],
    ["Target resource", text(work, ["target_resource_id"])],
    ["Assigned Node", text(work, ["assigned_node"])],
    ["Receipt operation", text(receipt, ["operation_id"])],
    ["Independent observation IDs", refs(verification.observation_ids)],
    ["Effect verification", text(verification, ["verdict"])],
    ["Work state", text(work, ["state"])],
    ["Input artifacts", refs(work.input_artifacts)],
    ["Output artifacts", refs(work.output_artifacts)],
    ["Evidence references", refs(work.evidence_refs)],
  ];
  return <section className="operations-work-chain" aria-label="Work execution chain"><h2>Work execution chain</h2><p>Values from the selected backend record. Receipt and observation are separate evidence; missing values remain UNKNOWN.</p><dl>{fields.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></section>;
}

export function OperationsConsole() {
  const [layout, setLayout] = useState(loadLayout);
  const { resolved, toggle } = useTheme();
  const t = (value: string) => layout.locale === "zh" ? translations[value] ?? value : value;
  const [snapshot, setSnapshot] = useState<OperationsSnapshot | null>(null);
  const collection = layout.active;
  const [query, setQuery] = useState("");
  const [human, setHuman] = useState<Human | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [details, setDetails] = useState<Row | null>(null);
  const [endpoint, setEndpoint] = useState(getConfig().url);
  const callbackHandled = useRef(false);
  const sequence = useRef(0);
  const refreshSequence = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const selectedId = useRef<string | null>(null);
  useEffect(() => { try { localStorage.setItem(layoutKey, JSON.stringify(layout)); } catch { /* Storage restrictions do not block observation. */ } }, [layout]);
  function selectCollection(key: Collection) {
    setLayout(current => ({ ...current, active: key, tabs: current.tabs.includes(key) ? current.tabs : [...current.tabs, key] }));
    setDetails(null); selectedId.current = null; setQuery("");
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === "Escape") { setDetails(null); selectedId.current = null; }
      if ((event.ctrlKey || event.metaKey) && event.key === "`") { event.preventDefault(); setLayout(current => ({ ...current, activityOpen: !current.activityOpen })); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const reload = useCallback(async () => {
    const request = ++refreshSequence.current;
    try { const value = await api<OperationsSnapshot>("/api/v1/control/operations"); if (request === refreshSequence.current) { setSnapshot(value); setError(""); } }
    catch (err) { if (request === refreshSequence.current) { setSnapshot(null); setDetails(null); setError(err instanceof Error ? err.message : "Runtime unavailable"); } }
  }, []);
  // A details view must track the latest authoritative record, including deletion.
  useEffect(() => {
    if (selectedId.current) setDetails(snapshot?.[collection].find(row => rowId(row) === selectedId.current) ?? null);
  }, [snapshot, collection]);
  useEffect(() => { void reload(); const timer = setInterval(() => { void reload(); }, 10000); return () => clearInterval(timer); }, [reload]);
  useEffect(() => {
    if (callbackHandled.current) return;
    const query = new URLSearchParams(window.location.search);
    if (query.has("error")) {
      callbackHandled.current = true;
      sessionStorage.removeItem(pkceKey);
      window.history.replaceState({}, "", window.location.pathname);
      setError("Human authentication was rejected by the identity provider");
      return;
    }
    const code = query.get("code");
    if (!code) {
      const controller = getConfig().url;
      let active = true;
      void api<Human>("/api/v1/control/human/session")
        .then(value => {
          if (active && getConfig().url === controller && typeof value.subject_id === "string" && Number.isFinite(value.expires_at) && value.expires_at * 1000 > Date.now()) setHuman(value);
        })
        .catch(() => { if (active) setHuman(null); });
      return () => { active = false; };
    }
    callbackHandled.current = true;
    const saved = sessionStorage.getItem(pkceKey);
    sessionStorage.removeItem(pkceKey);
    window.history.replaceState({}, "", window.location.pathname);
    try {
      const pending = JSON.parse(saved || "null") as { state: string; verifier: string; endpoint: string } | null;
      if (!pending || query.get("state") !== pending.state || pending.endpoint !== getConfig().url) throw new Error("Authentication state mismatch");
      void api<Human>("/api/v1/control/human/session", { method: "POST", body: JSON.stringify({ challenge_id: pending.state, code, code_verifier: pending.verifier }) })
        .then(value => { setHuman(value); void reload(); })
        .catch(err => setError(err instanceof Error ? err.message : "Authentication failed"));
    } catch (err) { setError(err instanceof Error ? err.message : "Authentication failed"); }
  }, [reload]);
  useEffect(() => {
    if (!human) return;
    // SSE carries durable monotonic transition evidence, then refreshes real state.
    const source = new EventSource(`${getConfig().url}/api/v1/control/events?since=${sequence.current}`, { withCredentials: true });
    source.addEventListener("control.state.changed", (event: MessageEvent<string>) => {
      const value = JSON.parse(event.data) as { sequence: number };
      sequence.current = Math.max(sequence.current, value.sequence);
      void reload();
    });
    const timer = setTimeout(() => { setHuman(null); source.close(); }, Math.max(0, human.expires_at * 1000 - Date.now()));
    return () => { clearTimeout(timer); source.close(); };
  }, [human, reload]);
  async function signIn() {
    setBusy(true);
    try {
      const bytes = crypto.getRandomValues(new Uint8Array(48));
      const verifier = btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
      const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
      const challenge = btoa(String.fromCharCode(...digest)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
      const result = await api<{ challenge_id: string; authorization_url: string }>("/api/v1/control/human/challenge", { method: "POST", body: JSON.stringify({ code_challenge: challenge }) });
      sessionStorage.setItem(pkceKey, JSON.stringify({ state: result.challenge_id, verifier, endpoint: getConfig().url }));
      window.location.assign(result.authorization_url);
    } catch (err) { setError(err instanceof Error ? err.message : "Authentication unavailable"); }
    finally { setBusy(false); }
  }
  async function action(kind: string, actionName: string, target: string) {
    setBusy(true);
    try {
      const path = "/api/v1/control/operations/actions";
      const body = { kind, action: actionName, target_id: target };
      const { nonce } = await api<{ nonce: string }>("/api/v1/control/human/nonce", { method: "POST", body: JSON.stringify({ method: "POST", path, body }) });
      await api(path, { method: "POST", headers: { "X-Control-Nonce": nonce }, body: JSON.stringify(body) });
      await reload();
    } catch (err) { setError(err instanceof Error ? err.message : "Governed action rejected"); }
    finally { setBusy(false); }
  }
  async function signOut() {
    setBusy(true);
    try {
      const path = "/api/v1/control/human/logout";
      const { nonce } = await api<{ nonce: string }>("/api/v1/control/human/nonce", { method: "POST", body: JSON.stringify({ method: "POST", path, body: {} }) });
      await api(path, { method: "POST", headers: { "X-Control-Nonce": nonce }, body: JSON.stringify({}) });
      setHuman(null);
      setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Sign out could not be confirmed"); }
    finally { setBusy(false); }
  }
  const enabled = !!human && human.expires_at * 1000 > Date.now() && !busy;
  const simulatedDevices = new Set((snapshot?.devices ?? []).filter(row => record(row.metadata).simulation === true && typeof row.device_id === "string" && row.device_id.length > 0).map(row => String(row.device_id)));
  const rows = snapshot?.[collection].filter(row => !query.trim() || JSON.stringify(row).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  return <main className="operations-console" aria-label="Operations console" lang={layout.locale === "zh" ? "zh-CN" : "en"}>
    <header className="operations-header"><div><p className="operations-eyebrow">APEIR / OPERATIONS</p><h1>{t("Execution & reality")}</h1><p>{t("Observe state, inspect evidence, govern the next action.")}</p></div>
      <div className="operations-controls"><button onClick={() => void reload()} disabled={busy}>{t("Refresh")}</button><button onClick={() => void signIn()} disabled={busy}>{t(human ? "Renew human session" : "Sign in as human")}</button>{human && <button onClick={() => void signOut()} disabled={busy}>{t("Sign out")}</button>}<button onClick={toggle} aria-label="Toggle theme">{resolved === "dark" ? "☀" : "☾"}</button><button onClick={() => setLayout(current => ({ ...current, locale: current.locale === "en" ? "zh" : "en" }))} aria-label="Change language">{layout.locale === "en" ? "中文" : "English"}</button></div>
    </header>
    <details className="operations-demo"><summary>Run the verified simulated demo</summary><p>Start with the source Quick Start. Run these CLI commands in an empty dedicated workspace; results and evidence come from the existing Runtime. Approval here is an explicit local OS-user action.</p><pre>apeir demo --workspace ./demo-match --phase prepare --json{"\n"}apeir demo --workspace ./demo-match --phase resume --approve-once --json</pre><p>SIMULATED · Runtime-service · Kernel not traversed. No physical or remote-human qualification.</p><a href="https://github.com/untrod/apeir/blob/main/examples/hello_runtime/README.md" target="_blank" rel="noreferrer">Failure scenarios and evidence guide</a></details>
    <details><summary>{t("Controller connection")}</summary><form onSubmit={event => { event.preventDefault(); try { const address = new URL(endpoint); if (address.username || address.password || address.search || address.hash || !(address.protocol === "https:" || (address.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(address.hostname)))) throw new Error("Controller requires HTTPS or loopback HTTP without credentials, query or fragment"); const url = address.href.replace(/\/$/, ""); setConfig({ url, token: url === getConfig().url ? getConfig().token : "" }); setHuman(null); setSnapshot(null); setDetails(null); selectedId.current = null; sequence.current = 0; void reload(); } catch (err) { setError(err instanceof Error ? err.message : "Invalid controller URL"); } }}><label>API URL <input aria-label="API URL" value={endpoint} onChange={event => setEndpoint(event.target.value)} /></label><button>{t("Connect")}</button></form></details>
    {error && <p role="alert" className="operations-error">{error}</p>}
    <section className="operations-health" aria-label="System health"><div><span className={`operations-badge ${!snapshot || snapshot.health.degraded ? "uncertain" : "healthy"}`}>{!snapshot ? "UNKNOWN" : snapshot.health.degraded ? "DEGRADED" : "HEALTHY"}</span><p>{human ? `Human: ${human.subject_id}` : t("Observe mode · human authentication required for actions")}</p></div>
      <div><strong>{snapshot?.works.length ?? "—"}</strong><span>{t("Work")}</span></div><div><strong>{snapshot?.nodes.length ?? "—"}</strong><span>{t("Nodes")}</span></div><div><strong>{snapshot?.devices.length ?? "—"}</strong><span>{t("Devices")}</span></div><div><strong>{snapshot?.approvals.filter(row => row.status === "PENDING").length ?? "—"}</strong><span>{t("Pending approvals")}</span></div>
    </section>
    <div className="operations-workbench">
    <nav className="operations-resources" aria-label="Runtime collections"><h2>{t("Workspace resources")}</h2>{collections.map(key => <button key={key} aria-pressed={collection === key} aria-label={layout.locale === "zh" ? t(key) : label(key)} onClick={() => selectCollection(key)}><span>{layout.locale === "zh" ? t(key) : label(key)}</span><small>{snapshot?.[key].length ?? "—"}</small></button>)}</nav>
    <div className="operations-center">
    <div className="operations-tabs" role="tablist" aria-label="Open views">{layout.tabs.map(key => <div key={key}><button role="tab" tabIndex={collection === key ? 0 : -1} aria-selected={collection === key} aria-controls="operations-records" onClick={() => selectCollection(key)} onKeyDown={event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); const index = event.key === "Home" ? 0 : event.key === "End" ? layout.tabs.length - 1 : (layout.tabs.indexOf(key) + (event.key === "ArrowRight" ? 1 : layout.tabs.length - 1)) % layout.tabs.length; selectCollection(layout.tabs[index]); (event.currentTarget.closest('[role="tablist"]')?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index])?.focus(); } }}>{layout.locale === "zh" ? t(key) : label(key)}</button>{layout.tabs.length > 1 && <button aria-label={`Close ${label(key)} view`} onClick={() => { const tabs = layout.tabs.filter(item => item !== key); setLayout(current => ({ ...current, tabs, active: current.active === key ? tabs[0] : current.active })); if (collection === key) { setDetails(null); selectedId.current = null; setQuery(""); } }}>×</button>}</div>)}</div>
    <label className="operations-search">{t("Search records")}<input ref={searchRef} aria-label="Search records" value={query} onChange={event => setQuery(event.target.value)} placeholder="Ctrl / ⌘ F" /></label>
    <section id="operations-records" role="tabpanel" aria-label={label(collection)} className="operations-records">
      {!snapshot ? <p>{t("Waiting for authoritative runtime data.")}</p> : snapshot[collection].length === 0 ? <p>{layout.locale === "zh" ? `暂无${t(collection)}记录。` : `No ${label(collection)} recorded.`}</p> : rows.length === 0 ? <p>{t("No matching records.")}</p> : rows.map((row, index) => {
        const id = rowId(row);
        const status = text(row, ["effective_status", "state", "status", "lifecycle", "connectivity_state", "event_type", "integrity"]);
        const simulated = record(row.metadata).simulation === true || simulatedDevices.has(typeof row.target_resource_id === "string" ? row.target_resource_id : "");
        return <article key={`${id}-${index}`}><div><button className="operations-identity" onClick={() => { selectedId.current = id; setDetails(row); }}>{id}</button><p>{text(row, ["objective", "execution_capability", "capability_id", "message", "name", "node_name", "target_ref", "resource_id"])}</p>{["works", "devices"].includes(collection) && <small>{simulated ? "SIMULATED" : "Execution scope not recorded"}</small>}{collection === "nodes" && <dl className="operations-node-state"><dt>{t("Trust")}</dt><dd>{text(row, ["trust_state", "trust_status"])}</dd><dt>{t("Connection")}</dt><dd>{text(row, ["connectivity_state", "connection_phase", "connectivity", "state"])}</dd></dl>}</div><span className="operations-badge">{status}</span><div className="operations-controls">
          {collection === "approvals" && row.status === "PENDING" && <><button disabled={!enabled} onClick={() => void action(collection, "approve_once", id)}>{t("Approve Once")}</button><button disabled={!enabled} onClick={() => void action(collection, "deny", id)}>{t("Deny")}</button></>}
          {collection === "works" && <><button disabled={!enabled} onClick={() => void action(collection, "interrupt", id)}>{t("Interrupt")}</button><button disabled={!enabled} onClick={() => void action(collection, "reconcile", id)}>{t("Reconcile")}</button>{snapshot.controls.actions.includes("resume") && <button disabled={!enabled} onClick={() => void action(collection, "resume", id)}>{t("Resume original workflow")}</button>}</>}
          {collection === "incidents" && <button disabled={!enabled || !!row.acknowledged} onClick={() => void action(collection, "acknowledge", id)}>{row.acknowledged ? "Acknowledged" : "Acknowledge"}</button>}
          {["grants", "credential_leases", "devices"].includes(collection) && <button disabled={!enabled} onClick={() => void action(collection, "revoke", id)}>{t("Revoke")}</button>}
        </div></article>;
      })}
    </section>
    </div>
    {details && <aside className="operations-evidence" aria-label="Evidence details" style={{ width: layout.inspectorWidth }}><header><h2>{t("Evidence details")}</h2><button onClick={() => { selectedId.current = null; setDetails(null); }}>{t("Close details")}</button></header><label className="operations-resize">{t("Resize evidence inspector")}<input aria-label="Resize evidence inspector" type="range" min="280" max="640" step="20" value={layout.inspectorWidth} onChange={event => setLayout(current => ({ ...current, inspectorWidth: Number(event.target.value) }))} /></label>{collection === "works" && <WorkEvidence work={details} />}<details open={collection !== "works"}><summary>{t("Raw backend record and diagnostics")}</summary><pre>{JSON.stringify(details, null, 2)}</pre></details></aside>}
    </div>
    <section className="operations-activity" aria-label="Activity panel"><button aria-expanded={layout.activityOpen} onClick={() => setLayout(current => ({ ...current, activityOpen: !current.activityOpen }))}>{t(layout.activityOpen ? "Hide activity" : "Show activity")} · {snapshot?.activity.length ?? "—"}</button>{layout.activityOpen && <div>{!snapshot ? <p>{t("Waiting for authoritative runtime data.")}</p> : snapshot.activity.length ? snapshot.activity.slice(-50).map((row, index) => <pre key={index}>{JSON.stringify(row)}</pre>) : <p>{t("No activity recorded.")}</p>}</div>}</section>
    <footer>{t("UNKNOWN requires reconciliation. Interrupt prevents future admission; an existing physical effect may still require observation.")}</footer>
  </main>;
}
