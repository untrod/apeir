/** Real runtime operations; every mutation returns to the existing Governance gate. */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, getConfig, setConfig } from "../lib/api";
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
const pkceKey = "apeir.human.pkce";

export function OperationsConsole() {
  const [snapshot, setSnapshot] = useState<OperationsSnapshot | null>(null);
  const [collection, setCollection] = useState<Collection>("works");
  const [human, setHuman] = useState<Human | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [details, setDetails] = useState<Row | null>(null);
  const [endpoint, setEndpoint] = useState(getConfig().url);
  const callbackHandled = useRef(false);
  const sequence = useRef(0);
  const reload = useCallback(async () => {
    try { setSnapshot(await api<OperationsSnapshot>("/api/v1/control/operations")); setError(""); }
    catch (err) { setError(err instanceof Error ? err.message : "Runtime unavailable"); }
  }, []);
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
  return <main className="operations-console" aria-label="Operations console">
    <header className="operations-header"><div><p className="operations-eyebrow">APEIR / OPERATIONS</p><h1>Execution &amp; reality</h1><p>Observe state, inspect evidence, govern the next action.</p></div>
      <div className="operations-controls"><button onClick={() => void reload()} disabled={busy}>Refresh</button><button onClick={() => void signIn()} disabled={busy}>{human ? "Renew human session" : "Sign in as human"}</button>{human && <button onClick={() => void signOut()} disabled={busy}>Sign out</button>}</div>
    </header>
    <details><summary>Controller connection</summary><form onSubmit={event => { event.preventDefault(); try { const address = new URL(endpoint); if (address.username || address.password || !(address.protocol === "https:" || (address.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(address.hostname)))) throw new Error("Controller requires HTTPS or loopback HTTP"); setConfig({ url: endpoint, token: endpoint === getConfig().url ? getConfig().token : "" }); setHuman(null); setSnapshot(null); void reload(); } catch (err) { setError(err instanceof Error ? err.message : "Invalid controller URL"); } }}><label>API URL <input aria-label="API URL" value={endpoint} onChange={event => setEndpoint(event.target.value)} /></label><button>Connect</button></form></details>
    {error && <p role="alert" className="operations-error">{error}</p>}
    <section className="operations-health" aria-label="System health"><div><span className={`operations-badge ${!snapshot || snapshot.health.degraded ? "uncertain" : "healthy"}`}>{!snapshot ? "UNKNOWN" : snapshot.health.degraded ? "DEGRADED" : "HEALTHY"}</span><p>{human ? `Human: ${human.subject_id}` : "Observe mode · human authentication required for actions"}</p></div>
      <div><strong>{snapshot?.works.length ?? "—"}</strong><span>Work</span></div><div><strong>{snapshot?.nodes.length ?? "—"}</strong><span>Nodes</span></div><div><strong>{snapshot?.devices.length ?? "—"}</strong><span>Devices</span></div><div><strong>{snapshot?.approvals.filter(row => row.status === "PENDING").length ?? "—"}</strong><span>Pending approvals</span></div>
    </section>
    <nav className="operations-tabs" aria-label="Runtime collections">{collections.map(key => <button key={key} aria-pressed={collection === key} onClick={() => { setCollection(key); setDetails(null); }}>{label(key)}</button>)}</nav>
    <section aria-label={label(collection)} className="operations-records">
      {!snapshot ? <p>Waiting for authoritative runtime data.</p> : snapshot[collection].length === 0 ? <p>No {label(collection)} recorded.</p> : snapshot[collection].map((row, index) => {
        const id = text(row, ["request_id", "work_id", "node_id", "device_id", "session_id", "grant_id", "lease_id", "run_id", "digest", "incident_id", "sequence"]);
        const status = text(row, ["effective_status", "state", "status", "lifecycle", "event_type", "integrity"]);
        return <article key={`${id}-${index}`}><div><button className="operations-identity" onClick={() => setDetails(row)}>{id}</button><p>{text(row, ["objective", "execution_capability", "capability_id", "message", "name", "target_ref", "resource_id"])}</p></div><span className="operations-badge">{status}</span><div className="operations-controls">
          {collection === "approvals" && row.status === "PENDING" && <><button disabled={!enabled} onClick={() => void action(collection, "approve_once", id)}>Approve Once</button><button disabled={!enabled} onClick={() => void action(collection, "deny", id)}>Deny</button></>}
          {collection === "works" && <><button disabled={!enabled} onClick={() => void action(collection, "interrupt", id)}>Interrupt</button><button disabled={!enabled} onClick={() => void action(collection, "reconcile", id)}>Reconcile</button>{snapshot.controls.actions.includes("resume") && <button disabled={!enabled} onClick={() => void action(collection, "resume", id)}>Resume original workflow</button>}</>}
          {collection === "incidents" && <button disabled={!enabled || !!row.acknowledged} onClick={() => void action(collection, "acknowledge", id)}>{row.acknowledged ? "Acknowledged" : "Acknowledge"}</button>}
          {["grants", "credential_leases", "devices"].includes(collection) && <button disabled={!enabled} onClick={() => void action(collection, "revoke", id)}>Revoke</button>}
        </div></article>;
      })}
    </section>
    {details && <aside className="operations-evidence" aria-label="Evidence details"><button onClick={() => setDetails(null)}>Close details</button><pre>{JSON.stringify(details, null, 2)}</pre></aside>}
    <footer>UNKNOWN requires reconciliation. Interrupt prevents future admission; an existing physical effect may still require observation.</footer>
  </main>;
}
