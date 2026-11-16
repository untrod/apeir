/** Automation is a bounded trigger consumer of the existing Workflow/Work owners. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  addAutomation, api, approvalAction, automationAction, captureRuntimeConnection, consumeAutomationDue,
  fetchAutomationHistory, fetchAutomations, subscribeRuntimeConfig,
  type AutomationHistory, type AutomationRun, type AutomationView,
} from "../lib/api";
import { useTheme } from "../theme";

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
const qualified = (item: AutomationView) => item.execution_scope === "runtime-service" && item.kernel_traversed === false && (
  (item.adapter === "simulated-reality" && item.qualification === "SIMULATED_TEMPLATE" && item.simulated === true) ||
  (item.adapter === "workflow" && item.qualification === "PURE_WORKFLOW" && item.simulated === false)
);
type Definition = { workflow_id: string; version: string };

export function AutomationInspector({ human, approvals }: { human: Human | null; approvals: Approval[] }) {
  const { locale } = useTheme();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [items, setItems] = useState<AutomationView[]>([]);
  const [selected, setSelected] = useState("");
  const [history, setHistory] = useState<AutomationHistory | null>(null);
  const [name, setName] = useState("Governed simulated firmware");
  const [firmware, setFirmware] = useState("2.0.0");
  const [trigger, setTrigger] = useState<"manual" | "schedule" | "cron">("manual");
  const [cron, setCron] = useState("0 * * * *");
  const [adapter, setAdapter] = useState<"simulated-reality" | "workflow">("simulated-reality");
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [workflow, setWorkflow] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [due, setDue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef(human);
  session.current = human;
  const alive = useRef(true);
  const requests = useRef(0);
  const catalogRequests = useRef(0);
  const operations = useRef(0);
  const inFlight = useRef(false);
  const outstanding = useRef(new Map<string, string>());
  const loggedIn = !!human && human.expires_at * 1000 > Date.now();
  const current = items.find(item => item.id === selected);
  const retire = useCallback(() => {
    requests.current++; catalogRequests.current++; operations.current++;
    inFlight.current = false; outstanding.current.clear();
    setItems([]); setSelected(""); setHistory(null); setDefinitions([]);
    setWorkflow(""); setInputs("{}"); setBusy(false); setCatalogBusy(false);
  }, []);

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
      retire();
      setError("Controller changed; sign in and load its authoritative Automation history.");
    });
    return () => { alive.current = false; unsubscribe(); };
  }, [retire]);
  useEffect(() => {
    retire();
    const original = operations.current;
    if (human && human.expires_at * 1000 > Date.now()) {
      void refresh().catch(cause => { if (alive.current && original === operations.current) setError(cause instanceof Error ? cause.message : "Automation history unavailable"); });
    }
  }, [human, refresh, retire]);

  async function loadDefinitions() {
    const guard = authorization();
    const request = ++catalogRequests.current;
    setCatalogBusy(true); setError("");
    try {
      guard();
      const result = await api<{ definitions: Definition[]; execution_scope: string }>("/api/v1/workflow");
      guard();
      if (request !== catalogRequests.current) return;
      if (result.execution_scope !== "runtime-service" || !Array.isArray(result.definitions) || result.definitions.length > 100 || !result.definitions.every(item => item && [item.workflow_id, item.version].every(value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value)))) throw new Error("Registered Workflow catalog is invalid");
      setDefinitions(result.definitions);
    } catch (cause) {
      if (alive.current && request === catalogRequests.current) setError(cause instanceof Error ? cause.message : "Workflow catalog unavailable");
    } finally { if (alive.current && request === catalogRequests.current) setCatalogBusy(false); }
  }

  async function perform(operation: (guard: () => void) => Promise<unknown>, id = selected) {
    if (inFlight.current) return;
    inFlight.current = true;
    const original = ++operations.current;
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
        if (alive.current && original === operations.current) { setItems([]); setHistory(null); setError("Outcome unconfirmed. Sign in and recover the original persisted history; do not create a replacement run."); }
      }
    } finally { if (alive.current && original === operations.current) { inFlight.current = false; setBusy(false); } }
  }
  const enabled = loggedIn && !busy;
  const pendingKey = outstanding.current.get(selected);
  const activeRun = history?.history.some(run => !terminal(run) || run.reconciliation_required || reconciledContinuation(run) || (current?.trigger === "cron" && !["completed", "cancelled"].includes(run.state)));
  return <section className="operations-automation" aria-label="Automation inspector">
    <h2>{t("Automations", "自动化")}</h2>
    <p>{t("Manual, one-shot or recurring UTC schedules. Each effect retains its original approval.", "支持手动、单次和 UTC 定时触发。操作仍需原有审批。")}</p>
    <details><summary>{t("Timer and execution scope", "定时器与执行范围")}</summary>
      <p>{t("Start the local timer explicitly; enabling a schedule alone does not start a service.", "启用计划不会自动启动服务。请明确启动本地定时器。")}</p>
      <code>apeir automation watch --workflow</code>
      <p>{t("Add --simulation to include simulated device schedules. Physical hardware is unqualified.", "添加 --simulation 可包含模拟设备计划；真实硬件尚未验收。")}</p>
      <p>execution_scope=runtime-service · kernel_traversed=false</p>
    </details>
    {!loggedIn && <p>{t("Sign in as human to read and manage Automations. Current server permissions are required for every request.", "请使用具备权限的人工身份登录后管理计划。每次请求均检查当前权限。")}</p>}
    {error && <p role="alert">{error}</p>}
    <button disabled={!enabled} onClick={() => void perform(async () => { await refresh(selected); })}>{t("Refresh Automation history", "刷新执行记录")}</button>
    <form aria-label={adapter === "workflow" ? "Schedule registered Workflow" : "Create simulated Automation"} onSubmit={event => {
      event.preventDefault();
      void perform(async guard => {
        const schedule = { name, trigger, ...(trigger === "schedule" ? { due_at: due } : {}), ...(trigger === "cron" ? { cron } : {}) };
        const selectedDefinition = definitions[Number(workflow)];
        if (adapter === "workflow" && (!workflow || !selectedDefinition)) throw new Error(t("Select a registered Workflow", "请选择已注册的工作流"));
        if (new TextEncoder().encode(inputs).length > 96 * 1024) throw new Error("Workflow inputs exceed 96 KiB");
        const created = await addAutomation(adapter === "workflow"
          ? { ...schedule, adapter, ...selectedDefinition, inputs: JSON.parse(inputs) }
          : { ...schedule, adapter, firmware_version: firmware }, guard);
        guard(); return created;
      }, "");
    }}>
      <label>{t("Source", "来源")}<select aria-label="Automation source" value={adapter} disabled={!enabled} onChange={event => {
        const value = event.target.value as typeof adapter;
        setAdapter(value);
        if (value === "workflow") { setName(t("Workflow schedule", "工作流计划")); void loadDefinitions(); }
        else setName(t("Governed simulated firmware", "受治理的固件模拟"));
      }}><option value="simulated-reality">{t("Simulated firmware", "固件模拟")}</option><option value="workflow">{t("Registered pure Workflow", "已注册的纯数据工作流")}</option></select></label>
      <label>{t("Name", "名称")}<input aria-label="Automation name" required maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>
      {adapter === "simulated-reality" ? <label>{t("Firmware version", "固件版本")}<input aria-label="Simulated firmware version" required value={firmware} onChange={event => setFirmware(event.target.value)} /></label> : <>
        <label>{t("Workflow version", "工作流版本")}<select aria-label="Registered Workflow" required value={workflow} onChange={event => setWorkflow(event.target.value)}><option value="">{catalogBusy ? t("Loading…", "加载中…") : t("Select registered version", "选择已注册版本")}</option>{definitions.map((item, index) => <option key={`${item.workflow_id}@${item.version}`} value={String(index)}>{item.workflow_id}@{item.version}</option>)}</select></label>
        <button type="button" disabled={!enabled || catalogBusy} onClick={() => void loadDefinitions()}>{t("Refresh Workflows", "刷新工作流")}</button>
        <details><summary>{t("Task inputs", "任务输入")}</summary><textarea aria-label="Workflow schedule inputs" maxLength={96 * 1024} value={inputs} onChange={event => setInputs(event.target.value)} /></details>
        <p>{t("TRANSFORM, WAIT and CONDITION only. WAIT is an immediate barrier. Models and commands require their own governed hosts.", "支持 TRANSFORM、WAIT 和 CONDITION。WAIT 是即时同步点。模型和命令需要单独的受治理执行主机。")}</p>
      </>}
      <label>{t("Trigger", "触发方式")}<select aria-label="Automation trigger" value={trigger} onChange={event => setTrigger(event.target.value as typeof trigger)}><option value="manual">{t("Manual", "手动")}</option><option value="schedule">{t("One-shot UTC due", "单次 UTC 定时")}</option><option value="cron">{t("Recurring Cron (UTC)", "循环 Cron（UTC）")}</option></select></label>
      {trigger === "schedule" && <label>{t("UTC due_at", "UTC 到期时间")}<input aria-label="UTC due timestamp" required placeholder="2026-11-16T12:00:00Z" value={due} onChange={event => setDue(event.target.value)} /></label>}
      {trigger === "cron" && <label>{t("Cron expression (UTC)", "Cron 表达式（UTC）")}<input aria-label="UTC Cron expression" required maxLength={128} placeholder="0 * * * *" value={cron} onChange={event => setCron(event.target.value)} /><small>{t("Minute · hour · day · month · weekday. Missed ticks coalesce; runs never overlap.", "分钟 · 小时 · 日期 · 月份 · 星期。漏触发合并，执行不重叠。")}</small></label>}
      <button disabled={!enabled || catalogBusy || (adapter === "workflow" && !workflow)}>{adapter === "workflow" ? t("Create Workflow schedule", "创建工作流计划") : t("Create simulated Automation", "创建模拟计划")}</button>
    </form>
    {!items.length && loggedIn && <p>{t("No authoritative Automations loaded.", "暂无已加载的计划。")}</p>}
    {items.map(item => <article key={item.id}>
      <h3>{item.name}</h3><p>{qualified(item) ? item.simulated ? t("SIMULATED", "模拟") : t("Pure Workflow", "纯数据工作流") : "UNQUALIFIED"} · {item.enabled ? t("ENABLED", "已启用") : t("DISABLED", "已停用")}</p>
      {!qualified(item) ? <p>{t("Legacy free-text record: UNQUALIFIED. It cannot execute a Workflow.", "旧版文本记录尚未获得执行资格，不能运行工作流。")}</p> : <>
        <p>{item.trigger === "cron" ? `Cron: ${item.cron} · UTC` : item.trigger === "schedule" ? `${t("One-shot UTC due", "单次 UTC 定时")}: ${item.due_at}` : t("Manual", "手动")}</p>
        <details><summary>{t("Definition details", "定义详情")}</summary><p>{item.id} · Workflow {item.workflow_id}@{item.version} · {item.definition_digest}</p></details>
        <button disabled={!enabled} onClick={() => void perform(async () => { await refresh(item.id); }, item.id)}>{t("Inspect history", "查看记录")} {item.name}</button>
        <button disabled={!enabled} onClick={() => void perform(guard => automationAction(item.enabled ? "disable" : "enable", item.id, {}, guard), item.id)}>{item.enabled ? t("Disable", "停用") : t("Enable", "启用")} {item.name}</button>
      </>}
    </article>)}
    {current && qualified(current) && <section aria-label="Original Automation history">
      <h3>{current.name} · {t("history", "执行记录")}</h3>
      <button disabled={!enabled || !current.enabled || !!pendingKey || !!activeRun || (current.trigger === "schedule" && (!current.due_at || Date.parse(current.due_at) > Date.now()))} onClick={() => {
        if (inFlight.current) return;
        if (current.trigger === "cron") { void perform(guard => consumeAutomationDue(current.id, guard), current.id); return; }
        const key = current.trigger === "schedule" ? `due:${current.due_at}` : `manual:${crypto.randomUUID()}`;
        outstanding.current.set(current.id, key);
        void perform(guard => automationAction("trigger", current.id, { trigger_key: key }, guard), current.id);
      }}>{current.trigger === "cron" ? t("Check due occurrence", "检查到期触发") : current.trigger === "schedule" ? t("Consume original due trigger", "执行原始到期触发") : t("Trigger manual run", "手动触发")}</button>
      {pendingKey && <p role="status">{t("Unconfirmed original trigger", "原始触发结果待确认")}: {pendingKey}. {t("Refresh persisted history to recover its original run. A replacement trigger is blocked.", "请刷新记录恢复原任务，不会创建替代任务。")}</p>}
      {history?.history.map(run => {
        const pending = Object.values(run.outputs).map(output => output.approval_request_id).filter((id): id is string => !!id && approvals.some(approval => approval.request_id === id && approval.status === "PENDING"));
        return <article key={run.run_id} aria-label={`Automation run ${run.run_id}`}>
          <h4>{run.run_id} · {run.state}</h4><p>{t("Original trigger", "原始触发")}: {run.trigger_key ?? "UNKNOWN"}</p>
          <p>{t("Cancellation", "取消请求")}: {run.cancellation_requested ? t("requested", "已提交") : t("not requested", "未提交")} · {t("Reconciliation", "结果对账")}: {run.reconciliation_required ? t("required", "需要") : t("not required", "无需")}</p>
          {pending.map(id => <div key={id}><p>{t("Original approval", "原始审批")}: {id}</p>{(["approve", "deny"] as const).map(decision => <button key={decision} disabled={!enabled || terminal(run) || run.cancellation_requested} onClick={() => void perform(async guard => {
            await approvalAction(id, decision, guard);
            guard();
            await automationAction("resume", current.id, { run_id: run.run_id }, guard);
          }, current.id)}>{decision === "approve" ? t("Approve Once", "批准一次") : t("Deny", "拒绝")}</button>)}</div>)}
          <button disabled={!enabled || (terminal(run) && !reconciledContinuation(run)) || run.cancellation_requested || run.reconciliation_required} onClick={() => void perform(guard => automationAction("resume", current.id, { run_id: run.run_id }, guard), current.id)}>{t("Resume original run", "恢复原始执行")}</button>
          <button disabled={!enabled || !run.reconciliation_required} onClick={() => void perform(guard => automationAction("reconcile", current.id, { run_id: run.run_id }, guard), current.id)}>{t("Reconcile original run", "核对原始结果")}</button>
          <button disabled={!enabled || ["completed", "cancelled"].includes(run.state) || run.cancellation_requested} onClick={() => void perform(guard => automationAction("cancel", current.id, { run_id: run.run_id }, guard), current.id)}>{t("Cancel original run", "取消原始执行")}</button>
          <details><summary>{t("Original Workflow / Work evidence", "原始工作流与任务证据")}</summary><pre>{JSON.stringify(run, null, 2)}</pre></details>
        </article>;
      })}
    </section>}
  </section>;
}
