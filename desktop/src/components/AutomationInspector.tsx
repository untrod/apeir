/** Automation is a bounded trigger consumer of the existing Workflow/Work owners. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  addAutomation, approvalAction, automationAction, captureRuntimeConnection,
  fetchAutomationHistory, fetchAutomations, subscribeRuntimeConfig,
  type AutomationHistory, type AutomationRun, type AutomationView,
} from "../lib/api";

type Human = { subject_id: string; expires_at: number };
type Approval = Record<string, unknown>;
const terminal = (run: AutomationRun) => ["completed", "cancelled", "failed", "compensation_failed"].includes(run.state);
const reconciledContinuation = (run: AutomationRun) => run.state === "failed"
  && !run.cancellation_requested && !run.reconciliation_required
  && run.works.length > 0 && run.works.every(work => work.state === "COMMITTED")
  && run.works.some(work => {
    const policy = work.execution_policy as Record<string, unknown> | undefined;
    const verification = work.effect_verification as Record<string, unknown> | undefined;
    return policy?.require_effect_verification === true && verification?.verdict === "MATCH"
      && typeof work.work_id === "string" && !!work.work_id
      && Object.values(run.outputs).some(output => output.work_id === work.work_id);
  });
const qualified = (item: AutomationView) => item.adapter === "simulated-reality" && item.qualification === "SIMULATED_TEMPLATE" && item.simulated === true && item.execution_scope === "runtime-service" && item.kernel_traversed === false;

export function AutomationInspector({ human, approvals }: { human: Human | null; approvals: Approval[] }) {
  const [items, setItems] = useState<AutomationView[]>([]);
  const [selected, setSelected] = useState("");
  const [history, setHistory] = useState<AutomationHistory | null>(null);
  const [name, setName] = useState("Governed simulated firmware");
  const [firmware, setFirmware] = useState("2.0.0");
  const [trigger, setTrigger] = useState<"manual" | "schedule">("manual");
  const [due, setDue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef(human);
  session.current = human;
  const alive = useRef(true);
  const requests = useRef(0);
  const outstanding = useRef(new Map<string, string>());
  const loggedIn = !!human && human.expires_at * 1000 > Date.now();
  const current = items.find(item => item.id === selected);

  const authorization = useCallback(() => {
    const original = session.current;
    const connection = captureRuntimeConnection();
    return () => {
      connection();
      if (!alive.current || !original || session.current !== original || original.expires_at * 1000 <= Date.now()) throw new Error("Human session changed; review the original Automation history.");
    };
  }, []);

  const refresh = useCallback(async (automationId = "") => {
    const guard = authorization();
    guard();
    const request = ++requests.current;
    const next = await fetchAutomations(guard);
    const id = automationId || next.automations.find(qualified)?.id || "";
    const item = next.automations.find(value => value.id === id);
    const persisted = item && qualified(item) ? await fetchAutomationHistory(id, guard) : null;
    guard();
    if (request !== requests.current) return;
    setItems(next.automations); setSelected(id); setHistory(persisted);
    const key = outstanding.current.get(id);
    if (key && persisted?.history.some(run => run.trigger_key === key)) outstanding.current.delete(id);
  }, [authorization]);

  useEffect(() => {
    alive.current = true;
    const unsubscribe = subscribeRuntimeConfig(() => {
      requests.current++; setItems([]); setSelected(""); setHistory(null);
      setError("Controller changed; sign in and load its authoritative Automation history.");
    });
    return () => { alive.current = false; unsubscribe(); };
  }, []);
  useEffect(() => {
    requests.current++; setItems([]); setHistory(null); setSelected("");
    if (human && human.expires_at * 1000 > Date.now()) {
      void refresh().catch(cause => { if (alive.current) setError(cause instanceof Error ? cause.message : "Automation history unavailable"); });
    }
  }, [human, refresh]);

  async function perform(operation: (guard: () => void) => Promise<unknown>, id = selected) {
    const guard = authorization();
    setBusy(true); setError("");
    try { guard(); const result = await operation(guard); guard(); await refresh(result && typeof result === "object" && "id" in result ? String(result.id) : id); }
    catch (cause) {
      try {
        guard();
        // Read persisted original state; never manufacture another trigger or Work.
        await refresh(id);
        guard();
        setError(`${cause instanceof Error ? cause.message : "Action unconfirmed"}. Inspect persisted original history before continuing.`);
      } catch {
        if (alive.current) { setItems([]); setHistory(null); setError("Outcome unconfirmed. Sign in and recover the original persisted history; do not create a replacement run."); }
      }
    } finally { if (alive.current) setBusy(false); }
  }
  const enabled = loggedIn && !busy;
  const pendingKey = outstanding.current.get(selected);
  const activeRun = history?.history.some(run => !terminal(run) || run.reconciliation_required || reconciledContinuation(run));
  return <section className="operations-automation" aria-label="Automation inspector">
    <h2>Automations</h2>
    <p>SIMULATED · execution_scope=runtime-service · kernel_traversed=false. Structured simulated firmware only; physical hardware remains unqualified.</p>
    <p>Manual or one-shot UTC due intent. Consume a due trigger explicitly below; no background cron or Workflow Recorder.</p>
    {!loggedIn && <p>Sign in as human to read and manage Automations. Current server permissions are required for every request.</p>}
    {error && <p role="alert">{error}</p>}
    <button disabled={!enabled} onClick={() => void perform(async () => { await refresh(selected); })}>Refresh Automation history</button>
    <form aria-label="Create simulated Automation" onSubmit={event => {
      event.preventDefault();
      void perform(async guard => {
        const created = await addAutomation({ adapter: "simulated-reality", name, firmware_version: firmware, trigger, ...(trigger === "schedule" ? { due_at: due } : {}) }, guard);
        guard(); return created;
      }, "");
    }}>
      <label>Name<input aria-label="Automation name" required maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>
      <label>Firmware version<input aria-label="Simulated firmware version" required value={firmware} onChange={event => setFirmware(event.target.value)} /></label>
      <label>Trigger<select aria-label="Automation trigger" value={trigger} onChange={event => setTrigger(event.target.value as "manual" | "schedule")}><option value="manual">Manual</option><option value="schedule">One-shot UTC due</option></select></label>
      {trigger === "schedule" && <label>UTC due_at<input aria-label="UTC due timestamp" required placeholder="2026-10-13T12:00:00Z" value={due} onChange={event => setDue(event.target.value)} /></label>}
      <button disabled={!enabled}>Create simulated Automation</button>
    </form>
    {!items.length && loggedIn && <p>No authoritative Automations loaded.</p>}
    {items.map(item => <article key={item.id}>
      <h3>{item.name}</h3><p>{item.id} · {qualified(item) ? "SIMULATED_TEMPLATE" : "UNQUALIFIED"} · {item.enabled ? "ENABLED" : "DISABLED"}</p>
      {!qualified(item) ? <p>Legacy free-text record: UNQUALIFIED. It cannot execute a Workflow.</p> : <>
        <p>Workflow {item.workflow_id} · Definition {item.definition_digest} · {item.trigger === "schedule" ? `One-shot UTC due: ${item.due_at}` : "Manual"}</p>
        <button disabled={!enabled} onClick={() => void perform(async () => { await refresh(item.id); }, item.id)}>Inspect history {item.name}</button>
        <button disabled={!enabled} onClick={() => void perform(guard => automationAction(item.enabled ? "disable" : "enable", item.id, {}, guard), item.id)}>{item.enabled ? "Disable" : "Enable"} {item.name}</button>
      </>}
    </article>)}
    {current && qualified(current) && <section aria-label="Original Automation history">
      <h3>{current.name} history</h3>
      <button disabled={!enabled || !current.enabled || !!pendingKey || !!activeRun || (current.trigger === "schedule" && (!current.due_at || Date.parse(current.due_at) > Date.now()))} onClick={() => {
        const key = current.trigger === "schedule" ? `due:${current.due_at}` : `manual:${crypto.randomUUID()}`;
        outstanding.current.set(current.id, key);
        void perform(guard => automationAction("trigger", current.id, { trigger_key: key }, guard), current.id);
      }}>{current.trigger === "schedule" ? "Consume original due trigger" : "Trigger manual run"}</button>
      {pendingKey && <p role="status">Unconfirmed original trigger: {pendingKey}. Refresh persisted history to recover its original run. A replacement trigger is blocked.</p>}
      {history?.history.map(run => {
        const pending = Object.values(run.outputs).map(output => output.approval_request_id).filter((id): id is string => !!id && approvals.some(approval => approval.request_id === id && approval.status === "PENDING"));
        return <article key={run.run_id} aria-label={`Automation run ${run.run_id}`}>
          <h4>{run.run_id} · {run.state}</h4><p>Original trigger: {run.trigger_key ?? "UNKNOWN"}</p>
          <p>Cancellation: {run.cancellation_requested ? "requested" : "not requested"} · Reconciliation: {run.reconciliation_required ? "required" : "not required"}</p>
          {pending.map(id => <div key={id}><p>Original approval: {id}</p>{(["approve", "deny"] as const).map(decision => <button key={decision} disabled={!enabled || terminal(run) || run.cancellation_requested} onClick={() => void perform(async guard => {
            await approvalAction(id, decision, guard);
            guard();
            await automationAction("resume", current.id, { run_id: run.run_id }, guard);
          }, current.id)}>{decision === "approve" ? "Approve Once" : "Deny"}</button>)}</div>)}
          <button disabled={!enabled || (terminal(run) && !reconciledContinuation(run)) || run.cancellation_requested || run.reconciliation_required} onClick={() => void perform(guard => automationAction("resume", current.id, { run_id: run.run_id }, guard), current.id)}>Resume original run</button>
          <button disabled={!enabled || !run.reconciliation_required} onClick={() => void perform(guard => automationAction("reconcile", current.id, { run_id: run.run_id }, guard), current.id)}>Reconcile original run</button>
          <button disabled={!enabled || terminal(run) || run.cancellation_requested} onClick={() => void perform(guard => automationAction("cancel", current.id, { run_id: run.run_id }, guard), current.id)}>Cancel original run</button>
          <details><summary>Original Workflow / Work evidence</summary><pre>{JSON.stringify(run, null, 2)}</pre></details>
        </article>;
      })}
    </section>}
  </section>;
}
