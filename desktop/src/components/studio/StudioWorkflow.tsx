import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  Background,
  Controls,
  Position,
  MarkerType,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Node,
  type NodeChange,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  ApiError,
  captureRuntimeConnection,
  governedStudioMutation as mutate,
  humanMutation,
  fetchModels,
  type ModelView,
} from "../../lib/api";
import {
  arrangeWorkflow,
  initialWorkflow,
  modelWorkflowStep,
  runnableStep,
  workflowDefinition,
  workflowDraft,
  workflowStepTypes,
  type WorkflowDefinition,
  type WorkflowDraft,
  type WorkflowStepType,
} from "../../lib/studioWorkflow";
import type { PanelProps } from "./StudioPanels";
import "./StudioWorkflow.css";

type Run = {
  run_id: string;
  workflow_id: string;
  workflow_version: string;
  state: string;
  step_states: Record<string, string>;
  outputs: Record<string, unknown>;
  error: string;
  definition_digest: string;
  inputs_digest: string;
  execution_scope: string;
  verification: string;
};
type Catalog = {
  step_types?: { type: string; available: boolean; actions?: string[] }[];
  data_bindings_versions?: number[];
  definitions: { workflow_id: string; version: string }[];
  runs: Pick<Run, "run_id" | "workflow_id" | "workflow_version" | "state">[];
};
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
export function StudioWorkflow({
  locale,
  onDraftChange,
  onDraftSnapshot,
}: PanelProps) {
  const zh = locale === "zh",
    t = (en: string, cn: string) => (zh ? cn : en);
  const flow = useRef<ReactFlowInstance | null>(null),
    fitFrame = useRef(0);
  const [runGraph, setRunGraph] = useState<WorkflowDefinition | null>(null);
  const [draft, setDraft] = useState(initialWorkflow),
    [selected, setSelected] = useState<string[]>([]),
    [catalog, setCatalog] = useState<Catalog | null>(null);
  const [measurements, setMeasurements] = useState<
    Record<string, { width: number; height: number }>
  >({});
  const [edgeSelection, setEdgeSelection] = useState<string[]>([]);
  const dragStart = useRef<WorkflowDraft | null>(null);
  const [past, setPast] = useState<WorkflowDraft[]>([]),
    [future, setFuture] = useState<WorkflowDraft[]>([]);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [run, setRun] = useState<Run | null>(null),
    [events, setEvents] = useState<unknown[]>([]);
  const [stepBindings, setStepBindings] = useState<Record<string, unknown>>({});
  const [kind, setKind] = useState<WorkflowStepType>("transform"),
    [inputs, setInputs] = useState("{}"),
    [paramsText, setParamsText] = useState("{}");
  const [nodeMenu, setNodeMenu] = useState<{ x: number; y: number; position: { x: number; y: number } } | null>(null);
  const nodeMenuElement = useRef<HTMLDivElement>(null);
  const canvasElement = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!nodeMenu) return;
    const menu = nodeMenuElement.current;
    (menu?.querySelector<HTMLButtonElement>("button:not(:disabled)") ?? menu)?.focus();
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Element && !nodeMenuElement.current?.contains(event.target)) setNodeMenu(null);
    };
    window.addEventListener("pointerdown", outside);
    return () => window.removeEventListener("pointerdown", outside);
  }, [nodeMenu]);
  const [bindingsText, setBindingsText] = useState("");
  const [models, setModels] = useState<ModelView[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [bindingTarget, setBindingTarget] = useState("value"),
    [bindingSource, setBindingSource] = useState("inputs"),
    [bindingPointer, setBindingPointer] = useState("/value");
  const [attempt, setAttempt] = useState<{
      fingerprint: string;
      key: string;
    } | null>(null),
    [dirty, setDirty] = useState(false);
  const active = useRef(true),
    file = useRef<HTMLInputElement>(null),
    currentDraft = useRef(draft);
  currentDraft.current = draft;
  const fitCanvas = useCallback(() => {
    cancelAnimationFrame(fitFrame.current);
    fitFrame.current = requestAnimationFrame(() => {
      fitFrame.current = requestAnimationFrame(() => {
        if (active.current)
          void flow.current?.fitView({ padding: 0.2, maxZoom: 1 });
      });
    });
  }, []);
  const hasRun = run !== null;
  const stepCount = draft.definition.steps.length;
  useEffect(() => {
    fitCanvas();
  }, [fitCanvas, hasRun, stepCount]);
  const reload = useCallback(async () => {
    const check = captureRuntimeConnection();
    const result = await api<Catalog>("/api/v1/workflow");
    check();
    if (active.current) setCatalog(result);
  }, []);
  useEffect(() => {
    active.current = true;
    void reload().catch((err) => {
      if (active.current) setError(String(err.message || err));
    });
    return () => {
      active.current = false;
      cancelAnimationFrame(fitFrame.current);
    };
  }, [reload]);
  useEffect(() => {
    onDraftChange(dirty || busy);
    onDraftSnapshot(
      dirty || busy
        ? [
            {
              path: "workflow-draft.json",
              originalSha256: "",
              content: JSON.stringify({ schemaVersion: 1, ...draft }, null, 2),
            },
            {
              path: "workflow-parameters-draft.txt",
              originalSha256: "",
              content: paramsText,
            },
            {
              path: "workflow-data-bindings-draft.json",
              originalSha256: "",
              content: bindingsText,
            },
            ...(attempt
              ? [
                  {
                    path: "workflow-request.json",
                    originalSha256: "",
                    content: JSON.stringify(attempt, null, 2),
                  },
                ]
              : []),
          ]
        : [],
    );
  }, [
    dirty,
    busy,
    draft,
    paramsText,
    bindingsText,
    attempt,
    onDraftChange,
    onDraftSnapshot,
  ]);
  const step = draft.definition.steps.find(
    (item) => item.step_id === selected[0],
  );
  const isModel = !!step && modelWorkflowStep(step);
  const modelHostAvailable =
    catalog?.step_types?.some(
      (type) =>
        type.type === "agent" &&
        type.available &&
        type.actions?.includes("model.invoke"),
    ) === true;
  const stepAvailable = (type: WorkflowStepType) =>
    catalog?.step_types?.some(item => item.type === type && item.available) === true &&
    (type === "agent" ? modelHostAvailable : !["capability", "connector", "command"].includes(type));
  const stepTitle = (type: WorkflowStepType) => ({
    agent: t("Model", "模型"), transform: t("Value / transform", "数据 / 转换"),
    approval: t("Human approval", "人工审批"), condition: t("Condition check", "条件检查"),
    wait: t("Wait barrier", "等待屏障"), capability: t("Capability", "能力"),
    connector: t("Connector", "连接器"), command: t("Command", "命令"),
  })[type];
  const needsModels = kind === "agent" || isModel;
  useEffect(() => {
    if (!needsModels) return;
    let current = true;
    const check = captureRuntimeConnection();
    void fetchModels()
      .then((result) => {
        check();
        if (current && active.current) {
          setModels(result.models);
          setModelsError("");
        }
      })
      .catch((error) => {
        try {
          check();
        } catch {
          return;
        }
        if (current && active.current)
          setModelsError(String(error.message || error));
      });
    return () => {
      current = false;
    };
  }, [needsModels]);
  let modelParams: Record<string, unknown> | null = null;
  if (isModel) {
    try {
      const value: unknown = JSON.parse(paramsText);
      if (value && typeof value === "object" && !Array.isArray(value))
        modelParams = value as Record<string, unknown>;
    } catch {
      /* The original JSON draft stays intact until it is valid. */
    }
  }
  function updateModelParams(values: Record<string, unknown>) {
    if (!modelParams) return;
    setParamsText(JSON.stringify({ ...modelParams, ...values }, null, 2));
    setDirty(true);
  }
  const paramsPending =
    !!step &&
    (paramsText !== JSON.stringify(step.params || {}, null, 2) ||
      bindingsText !==
        (step.data_bindings
          ? JSON.stringify(step.data_bindings, null, 2)
          : ""));
  const pendingParameters = useRef(false);
  pendingParameters.current = paramsPending;
  // A new selection must not mistake the previous editor text for its own draft
  // when a keyboard action arrives before an ordinary passive effect runs.
  useLayoutEffect(() => {
    setParamsText(JSON.stringify(step?.params || {}, null, 2));
    setBindingsText(
      step?.data_bindings ? JSON.stringify(step.data_bindings, null, 2) : "",
    );
    setBindingSource(
      step?.depends_on?.length ? `step:${step.depends_on[0]}` : "inputs",
    );
    setBindingTarget(step && modelWorkflowStep(step) ? "input" : "value");
  }, [step]);
  function commit(next: WorkflowDraft, previous = currentDraft.current) {
    if (JSON.stringify(next) === JSON.stringify(previous)) return;
    currentDraft.current = next;
    setPast((items) => [...items.slice(-49), previous]);
    setFuture([]);
    setDraft(next);
    setDirty(true);
    setNotice("");
    if (
      JSON.stringify(next.definition) !== JSON.stringify(previous.definition)
    ) {
      setRun(null);
      setRunGraph(null);
      setEvents([]);
      setStepBindings({});
    }
  }
  function safely(change: () => void) {
    try {
      change();
      setError("");
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }
  function edit(
    change: (definition: WorkflowDefinition) => WorkflowDefinition,
    applyPendingParameters = false,
    positions?: WorkflowDraft["positions"],
  ) {
    if (pendingParameters.current && !applyPendingParameters) {
      setError(
        t(
          "Apply or discard parameter changes before editing the Workflow.",
          "编辑工作流前请应用或放弃参数修改。",
        ),
      );
      return false;
    }
    return safely(() => {
      const current = currentDraft.current;
      const definition = workflowDefinition(
        change(structuredClone(current.definition)),
      );
      commit({ ...current, definition, positions: positions ?? current.positions });
    });
  }
  function addStep(type: WorkflowStepType, position?: { x: number; y: number }) {
    if (!stepAvailable(type)) return;
    const id = `step-${crypto.randomUUID().slice(0, 8)}`;
    const added = edit(d => ({ ...d, steps: [...d.steps, {
      step_id: id, step_type: type,
      ...(type === "agent" ? { action: "model.invoke", approval_required: true } : {}),
      params: type === "agent" ? { model_id: "", instruction: "", max_tokens: 512, max_cost_usd: 0.01 } : type === "transform" ? { value: "" } : {},
    }] }), false, position ? { ...currentDraft.current.positions, [id]: position } : undefined);
    if (added) { setSelected([id]); setKind(type); setNodeMenu(null); }
  }
  async function action(work: () => Promise<void>) {
    const check = captureRuntimeConnection();
    setBusy(true);
    setError("");
    try {
      await work();
      check();
    } catch (err) {
      if (active.current)
        setError(
          `${err instanceof Error ? err.message : String(err)}${err instanceof ApiError && err.details?.approval_request_id ? ` · Approval: ${err.details.approval_request_id}` : ""} · ${t("Inspect the original request before retrying.", "重试前请核对原始请求。")}`,
        );
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function inspect(id: string, graph: WorkflowDefinition | null = null) {
    const check = captureRuntimeConnection();
    const detail = await api<{
      run: Run;
      events: unknown[];
      step_bindings?: Record<string, unknown>;
    }>(`/api/v1/workflow/runs/${encodeURIComponent(id)}`);
    check();
    if (active.current) {
      setRun(detail.run);
      setRunGraph(graph);
      setEvents(detail.events);
      setStepBindings(detail.step_bindings ?? {});
    }
  }
  const graphMatchesRun =
    !!runGraph && JSON.stringify(runGraph) === JSON.stringify(draft.definition);
  const nodes: Node[] = draft.definition.steps.map((item, index) => ({
    id: item.step_id,
    type: "default",
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    position: draft.positions[item.step_id] || { x: index * 220, y: 0 },
    selected: selected.includes(item.step_id),
    measured: measurements[item.step_id],
    data: {
      label: (
        <>
          <strong title={item.step_id}>{item.step_type === "agent" && !modelWorkflowStep(item) ? t("Agent", "智能体") : stepTitle(item.step_type)}</strong>
          <span>
            {modelWorkflowStep(item) ? "MODEL" : item.step_type.toUpperCase()} ·{" "}
            {(graphMatchesRun && run?.step_states[item.step_id]) ||
              (modelWorkflowStep(item)
                ? !modelHostAvailable
                  ? "BLOCKED"
                  : runnableStep(item)
                    ? "CONFIGURED"
                    : "UNCONFIGURED"
                : runnableStep(item)
                  ? "READY"
                  : "UNSUPPORTED")}
          </span>
        </>
      ),
    },
  }));
  const edges: Edge[] = draft.definition.steps.flatMap((item) =>
    (item.depends_on || []).map((source) => ({
      id: `${source}:${item.step_id}`,
      source,
      target: item.step_id,
      selected: edgeSelection.includes(`${source}:${item.step_id}`),
      ariaLabel: `${source} → ${item.step_id}`,
      label:
        Object.entries(item.data_bindings?.inputs ?? {})
          .filter(([, ref]) => ref.source === "step" && ref.step_id === source)
          .map(([target]) => target)
          .join(", ") || undefined,
      labelStyle: { fill: "var(--nous-text)" },
      labelBgStyle: { fill: "var(--nous-bg)" },
    })),
  );
  function nodeChanges(changes: NodeChange[]) {
    const next = applyNodeChanges(changes, nodes);
    if (changes.some((change) => change.type === "select")) {
      if (pendingParameters.current)
        setError(
          t(
            "Apply or discard parameter changes before selecting another step.",
            "切换节点前请应用或放弃参数修改。",
          ),
        );
      else
        setSelected(
          next.filter((node) => node.selected).map((node) => node.id),
        );
    }
    if (changes.some((change) => change.type === "dimensions"))
      setMeasurements((previous) => {
        const result = Object.fromEntries(
          Object.entries(previous).filter(([id]) =>
            draft.definition.steps.some((step) => step.step_id === id),
          ),
        );
        for (const change of changes)
          if (change.type === "dimensions" && change.dimensions)
            result[change.id] = change.dimensions;
        return result;
      });
    if (
      changes.some(
        (change) => change.type === "position" && change.dragging !== true,
      )
    ) {
      commit(
        {
          ...draft,
          positions: Object.fromEntries(
            next.map((node) => [node.id, node.position]),
          ),
        },
        dragStart.current || draft,
      );
      dragStart.current = null;
    } else if (changes.some((change) => change.type === "position"))
      setDraft((value) => ({
        ...value,
        positions: Object.fromEntries(
          next.map((node) => [node.id, node.position]),
        ),
      }));
  }
  function connect(connection: Connection) {
    if (!connection.source || !connection.target) return;
    edit((d) => ({
      ...d,
      steps: d.steps.map((item) =>
        item.step_id === connection.target
          ? {
              ...item,
              depends_on: [
                ...new Set([...(item.depends_on || []), connection.source!]),
              ],
            }
          : item,
      ),
    }));
  }
  function restore(value: unknown) {
    if (
      dirty &&
      !window.confirm(
        t("Replace the unsaved workflow draft?", "替换未保存的工作流草稿？"),
      )
    )
      return;
    safely(() => {
      const next = workflowDraft(value);
      commit(next);
      setSelected([]);
      fitCanvas();
    });
  }
  return (
    <section className="studio-workflow" aria-label="Workflow Builder">
      <header className="studio-workflow-toolbar">
        <input
          aria-label="Workflow ID"
          maxLength={128}
          value={draft.definition.workflow_id}
          onChange={(e) =>
            commit({
              ...draft,
              definition: { ...draft.definition, workflow_id: e.target.value },
            })
          }
        />
        <input
          aria-label="Workflow version"
          maxLength={128}
          value={draft.definition.version}
          onChange={(e) =>
            commit({
              ...draft,
              definition: { ...draft.definition, version: e.target.value },
            })
          }
        />
        <button
          disabled={!past.length || paramsPending}
          onClick={() => {
            setFuture((items) => [draft, ...items]);
            setDraft(past[past.length - 1]);
            setPast((items) => items.slice(0, -1));
            setDirty(true);
          }}
        >
          {t("Undo", "撤销")}
        </button>
        <button
          disabled={!future.length || paramsPending}
          onClick={() => {
            setPast((items) => [...items, draft]);
            setDraft(future[0]);
            setFuture((items) => items.slice(1));
            setDirty(true);
          }}
        >
          {t("Redo", "重做")}
        </button>
        <button
          onClick={() =>
            safely(() => {
              commit({
                ...draft,
                positions: arrangeWorkflow(draft.definition),
              });
              fitCanvas();
            })
          }
        >
          {t("Arrange", "整理")}
        </button>
        <button
          disabled={busy || paramsPending}
          onClick={() =>
            void action(async () => {
              const result = await api<{
                runnable: boolean;
                unsupported_steps: string[];
              }>("/api/v1/workflow/validate", {
                method: "POST",
                body: JSON.stringify({
                  definition: workflowDefinition(draft.definition),
                }),
              });
              if (active.current)
                setNotice(
                  result.runnable
                    ? "VALID · runtime-service"
                    : `UNSUPPORTED · ${result.unsupported_steps.join(", ")}`,
                );
            })
          }
        >
          {t("Validate", "验证")}
        </button>
        <button
          disabled={busy || paramsPending}
          onClick={() =>
            void action(async () => {
              await mutate("/api/v1/workflow/register", {
                definition: workflowDefinition(draft.definition),
              });
              if (active.current) {
                setNotice(
                  `REGISTERED · ${draft.definition.workflow_id}@${draft.definition.version}`,
                );
                await reload();
              }
            })
          }
        >
          {t("Register", "注册")}
        </button>
        <button
          disabled={
            busy ||
            paramsPending ||
            (draft.definition.steps.some((item) => item.data_bindings) &&
              !catalog?.data_bindings_versions?.includes(1)) ||
            draft.definition.steps.some(
              (item) =>
                !runnableStep(item) ||
                (modelWorkflowStep(item) && !modelHostAvailable),
            )
          }
          onClick={() =>
            void action(async () => {
              workflowDefinition(draft.definition);
              const parsed = JSON.parse(inputs);
              const fingerprint = JSON.stringify([draft.definition, parsed]);
              const original =
                attempt?.fingerprint === fingerprint
                  ? attempt
                  : { fingerprint, key: `studio-${crypto.randomUUID()}` };
              setAttempt(original);
              const result = await mutate<Run>("/api/v1/workflow/run", {
                workflow_id: draft.definition.workflow_id,
                version: draft.definition.version,
                inputs: parsed,
                definition: draft.definition,
                idempotency_key: original.key,
              });
              if (active.current) {
                await inspect(result.run_id, draft.definition);
                await reload();
              }
            })
          }
        >
          {t("Run", "运行")}
        </button>
        <details>
          <summary>
            {t("Draft", "草稿")}
            {dirty && <span> · {t("Unsaved", "未保存")}</span>}
          </summary>
          <button onClick={() => file.current?.click()}>
            {t("Import", "导入")}
          </button>
          <button
            onClick={() =>
              safely(() =>
                download("workflow.json", workflowDefinition(draft.definition)),
              )
            }
          >
            {t("Export definition", "导出定义")}
          </button>
          <button
            disabled={paramsPending}
            onClick={() => {
              safely(() => {
                workflowDraft({ schemaVersion: 1, ...draft });
                download("workflow-draft.json", { schemaVersion: 1, ...draft });
                setDirty(false);
              });
            }}
          >
            {t("Save draft", "保存草稿")}
          </button>
        </details>
        <input
          ref={file}
          type="file"
          hidden
          accept=".json,application/json"
          onChange={(event) => {
            const input = event.currentTarget,
              selectedFile = input.files?.[0];
            if (selectedFile) {
              if (selectedFile.size > 128 * 1024)
                setError("Draft exceeds 128 KiB");
              else
                void selectedFile
                  .text()
                  .then((text) => restore(JSON.parse(text)))
                  .catch((err) => setError(String(err.message)));
            }
            input.value = "";
          }}
        />
      </header>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="studio-workflow-body">
        <aside>
          <select
            aria-label="Step type"
            value={kind}
            onChange={(e) => setKind(e.target.value as WorkflowStepType)}
          >
            {workflowStepTypes.map((type) => (
              <option
                key={type}
                value={type}
                disabled={!stepAvailable(type)}
              >
                {stepTitle(type)}{!stepAvailable(type) ? ` · ${t("UNSUPPORTED", "不支持")}` : type === "agent" ? ` · ${t("APPROVAL", "需审批")}` : ""}
              </option>
            ))}
          </select>
          <button disabled={paramsPending || !stepAvailable(kind)} onClick={() => addStep(kind)}>
            {t("Add step", "添加节点")}
          </button>
          <button
            disabled={!selected.length || paramsPending}
            onClick={() =>
              edit((d) => ({
                ...d,
                steps: d.steps
                  .filter((item) => !selected.includes(item.step_id))
                  .map((item) => ({
                    ...item,
                    depends_on: item.depends_on?.filter(
                      (id) => !selected.includes(id),
                    ),
                  })),
              }))
            }
          >
            {t("Delete selected", "删除所选")}
          </button>
          <button
            disabled={!selected.length || paramsPending}
            onClick={() =>
              edit((d) => {
                const map = Object.fromEntries(
                  selected.map((id) => [
                    id,
                    `step-${crypto.randomUUID().slice(0, 8)}`,
                  ]),
                );
                return {
                  ...d,
                  steps: [
                    ...d.steps,
                    ...d.steps
                      .filter((item) => selected.includes(item.step_id))
                      .map((item) => ({
                        ...item,
                        step_id: map[item.step_id],
                        depends_on: item.depends_on?.map((id) => map[id] || id),
                        ...(item.data_bindings
                          ? {
                              data_bindings: {
                                ...item.data_bindings,
                                inputs: Object.fromEntries(
                                  Object.entries(
                                    item.data_bindings.inputs ?? {},
                                  ).map(([target, ref]) => [
                                    target,
                                    ref.source === "step"
                                      ? {
                                          ...ref,
                                          step_id:
                                            map[ref.step_id] || ref.step_id,
                                        }
                                      : ref,
                                  ]),
                                ),
                              },
                            }
                          : {}),
                      })),
                  ],
                };
              })
            }
          >
            {t("Duplicate", "复制")}
          </button>
          {step && (
            <>
              <strong title={step.step_id}>{step.step_type === "agent" && !isModel ? t("Agent", "智能体") : stepTitle(step.step_type)}</strong>
              {isModel && (
                <fieldset disabled={!modelParams}>
                  <legend>{t("Model", "模型")}</legend>
                  <label>
                    {t("Registered model", "已注册模型")}
                    <select
                      aria-label="Workflow model"
                      value={String(modelParams?.model_id ?? "")}
                      onChange={(e) =>
                        updateModelParams({ model_id: e.target.value })
                      }
                    >
                      <option value="">
                        {t("Choose a model", "选择模型")}
                      </option>
                      {!!modelParams?.model_id &&
                        !models.some(
                          (m) => m.model_id === modelParams?.model_id,
                        ) && (
                          <option value={String(modelParams.model_id)}>
                            {String(modelParams.model_id)} · UNKNOWN
                          </option>
                        )}
                      {models.map((m) => (
                        <option key={m.model_id} value={m.model_id}>
                          {m.model_id} · {m.state} / {m.health}
                        </option>
                      ))}
                    </select>
                  </label>
                  {modelsError && <span role="status">{modelsError}</span>}
                  <label>
                    {t("Instruction", "任务说明")}
                    <textarea
                      aria-label="Model instruction"
                      maxLength={16384}
                      value={String(modelParams?.instruction ?? "")}
                      onChange={(e) =>
                        updateModelParams({ instruction: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    {t("Maximum output Tokens", "输出 Token 上限")}
                    <input
                      aria-label="Model token budget"
                      type="number"
                      min={1}
                      max={32768}
                      value={Number(modelParams?.max_tokens ?? 512)}
                      onChange={(e) =>
                        updateModelParams({
                          max_tokens: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    {t("Cost limit (USD)", "费用上限（美元）")}
                    <input
                      aria-label="Model cost budget"
                      type="number"
                      min={0}
                      step="0.01"
                      value={Number(modelParams?.max_cost_usd ?? 0)}
                      onChange={(e) =>
                        updateModelParams({
                          max_cost_usd: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                </fieldset>
              )}
              {step.step_type === "transform" && typeof step.params?.value === "string" && <label>
                {t("Value", "内容")}<textarea aria-label="Transform value" value={(() => { try { const p = JSON.parse(paramsText); return typeof p.value === "string" ? p.value : ""; } catch { return ""; } })()} onChange={event => {
                  try { setParamsText(JSON.stringify({ ...JSON.parse(paramsText), value: event.target.value }, null, 2)); setDirty(true); }
                  catch { setError(t("Fix the parameter JSON first.", "请先修正参数 JSON。")); }
                }} />
              </label>}
              <details className="workflow-parameters">
                <summary>{t("Advanced parameters", "高级参数")}</summary><code>{step.step_id}</code>
                <label>{t("Parameters", "参数")}
                  <textarea aria-label="Step parameters" value={paramsText} maxLength={32768} onChange={event => { setParamsText(event.target.value); setDirty(true); }} />
                </label>
              </details>
              <button
                disabled={!paramsPending}
                onClick={() => {
                  const applied = edit(
                    (d) => ({
                      ...d,
                      steps: d.steps.map((item) =>
                        item.step_id === step.step_id
                          ? (() => {
                              const updated = {
                                ...item,
                                params: JSON.parse(paramsText),
                              };
                              if (bindingsText.trim())
                                updated.data_bindings =
                                  JSON.parse(bindingsText);
                              else delete updated.data_bindings;
                              return updated;
                            })()
                          : item,
                      ),
                    }),
                    true,
                  );
                  if (applied)
                    setParamsText(
                      JSON.stringify(
                        currentDraft.current.definition.steps.find(
                          (item) => item.step_id === step.step_id,
                        )?.params || {},
                        null,
                        2,
                      ),
                    );
                }}
              >
                {t("Apply parameters", "应用参数")}
              </button>
              <button
                disabled={!paramsPending}
                onClick={() => {
                  setParamsText(JSON.stringify(step.params || {}, null, 2));
                  setBindingsText(
                    step.data_bindings
                      ? JSON.stringify(step.data_bindings, null, 2)
                      : "",
                  );
                }}
              >
                {t("Discard parameters", "放弃参数")}
              </button>
              <details>
                <summary>
                  {t("Data bindings", "数据绑定")} ·{" "}
                  {Object.keys(step.data_bindings?.inputs ?? {}).length}
                </summary>
                <label>
                  {t("Target parameter", "目标参数")}
                  <input
                    aria-label="Binding target"
                    value={bindingTarget}
                    onChange={(event) => setBindingTarget(event.target.value)}
                  />
                </label>
                <label>
                  {t("Source", "来源")}
                  <select
                    aria-label="Binding source"
                    value={bindingSource}
                    onChange={(event) => setBindingSource(event.target.value)}
                  >
                    <option value="inputs">
                      {t("Run inputs", "运行输入")}
                    </option>
                    {(step.depends_on ?? []).map((id) => (
                      <option key={id} value={`step:${id}`}>
                        {id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("JSON pointer", "JSON 路径")}
                  <input
                    aria-label="Binding pointer"
                    value={bindingPointer}
                    onChange={(event) => setBindingPointer(event.target.value)}
                  />
                </label>
                <button
                  disabled={paramsPending}
                  onClick={() =>
                    edit((d) => ({
                      ...d,
                      steps: d.steps.map((item) => {
                        if (item.step_id !== step.step_id) return item;
                        const params = { ...item.params };
                        delete params[bindingTarget];
                        const reference =
                          bindingSource === "inputs"
                            ? {
                                source: "inputs" as const,
                                pointer: bindingPointer,
                              }
                            : {
                                source: "step" as const,
                                step_id: bindingSource.slice(5),
                                pointer: bindingPointer,
                              };
                        return {
                          ...item,
                          params,
                          data_bindings: {
                            schema_version: 1,
                            ...item.data_bindings,
                            inputs: {
                              ...item.data_bindings?.inputs,
                              [bindingTarget]: reference,
                            },
                          },
                        };
                      }),
                    }))
                  }
                >
                  {t("Bind input", "绑定输入")}
                </button>
                {Object.entries(step.data_bindings?.inputs ?? {}).map(
                  ([target, reference]) => (
                    <div key={target}>
                      <span>
                        {target} ←{" "}
                        {reference.source === "step"
                          ? reference.step_id
                          : "inputs"}
                        {reference.pointer}
                      </span>
                      <button
                        disabled={paramsPending}
                        aria-label={`Remove binding ${target}`}
                        onClick={() =>
                          edit((d) => ({
                            ...d,
                            steps: d.steps.map((item) => {
                              if (
                                item.step_id !== step.step_id ||
                                !item.data_bindings
                              )
                                return item;
                              const inputs = { ...item.data_bindings.inputs };
                              delete inputs[target];
                              return {
                                ...item,
                                data_bindings: {
                                  ...item.data_bindings,
                                  inputs,
                                },
                              };
                            }),
                          }))
                        }
                      >
                        {t("Remove", "移除")}
                      </button>
                    </div>
                  ),
                )}
                <label>
                  {t("Data contract / schemas", "数据契约 / Schema")}
                  <textarea
                    aria-label="Step data bindings"
                    value={bindingsText}
                    maxLength={32768}
                    onChange={(event) => {
                      setBindingsText(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
              </details>
              <p>
                {step.step_type === "wait"
                  ? t(
                      "WAIT is an immediate barrier, not a timed delay.",
                      "WAIT 是即时屏障，不是计时延迟。",
                    )
                  : step.step_type === "approval"
                    ? t(
                        "Approval must come from the original trusted human host.",
                        "审批必须由原始可信人工入口提供。",
                      )
                    : ""}
              </p>
            </>
          )}
          <details className="workflow-history"><summary>{t("Inputs & history", "输入与历史")}</summary>
          <label>
            {t("Run inputs", "运行输入")}
            <textarea
              aria-label="Workflow inputs"
              value={inputs}
              onChange={(e) => setInputs(e.target.value)}
            />
          </label>
          <button disabled={busy} onClick={() => void action(reload)}>
            {t("Refresh history", "刷新历史")}
          </button>
          <label>
            {t("Definitions", "已有定义")}
            <select
              aria-label="Registered workflows"
              value=""
              onChange={(e) => {
                const selectedDefinition =
                  catalog?.definitions[Number(e.target.value)];
                if (selectedDefinition)
                  void action(async () => {
                    const result = await api<{
                      definition: WorkflowDefinition;
                    }>(
                      `/api/v1/workflow/definitions/${encodeURIComponent(selectedDefinition.workflow_id)}/${encodeURIComponent(selectedDefinition.version)}`,
                    );
                    if (active.current) restore(result.definition);
                  });
              }}
            >
              <option value="">—</option>
              {catalog?.definitions.map((item, index) => (
                <option
                  key={`${item.workflow_id}@${item.version}`}
                  value={index}
                >
                  {item.workflow_id}@{item.version}
                </option>
              ))}
            </select>
          </label>
          {catalog?.runs.slice(0, 30).map((item) => (
            <button
              className="studio-workflow-history"
              key={item.run_id}
              onClick={() => void action(() => inspect(item.run_id))}
            >
              {item.workflow_id} · {item.state}
              <small>{item.run_id}</small>
            </button>
          ))}
          </details>
        </aside>
        <div className="studio-workflow-canvas" ref={canvasElement} tabIndex={0} aria-label={t("Workflow canvas", "工作流画布")} onKeyDown={event => {
          if (event.key === "ContextMenu" || event.shiftKey && event.key === "F10") {
            event.preventDefault(); const rect = event.currentTarget.getBoundingClientRect();
            const point = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
            setNodeMenu({ ...point, position: flow.current?.screenToFlowPosition(point) ?? { x: 0, y: 0 } });
          }
        }}>
          <ReactFlow
            onPaneContextMenu={event => {
              event.preventDefault(); const point = { x: event.clientX, y: event.clientY };
              setNodeMenu({ ...point, position: flow.current?.screenToFlowPosition(point) ?? { x: 0, y: 0 } });
            }}
            onMoveStart={() => setNodeMenu(null)}
            onInit={(instance) => {
              flow.current = instance;
              fitCanvas();
            }}
            fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
            nodes={nodes}
            edges={edges}
            onNodesChange={nodeChanges}
            onNodeDragStart={() => {
              dragStart.current = structuredClone(draft);
            }}
            onEdgesChange={(changes) =>
              setEdgeSelection((previous) => {
                const next = new Set(previous);
                for (const change of changes)
                  if (change.type === "select") {
                    if (change.selected) next.add(change.id);
                    else next.delete(change.id);
                  }
                return [...next];
              })
            }
            onConnect={connect}
            onBeforeDelete={async () => !pendingParameters.current}
            onDelete={({ nodes: deletedNodes, edges: deletedEdges }) =>
              edit((d) => ({
                ...d,
                steps: d.steps
                  .filter(
                    (item) =>
                      !deletedNodes.some((node) => node.id === item.step_id),
                  )
                  .map((item) => ({
                    ...item,
                    depends_on: item.depends_on?.filter(
                      (source) =>
                        !deletedNodes.some((node) => node.id === source) &&
                        !deletedEdges.some(
                          (edge) =>
                            edge.source === source &&
                            edge.target === item.step_id,
                        ),
                    ),
                  })),
              }))
            }
            deleteKeyCode={["Backspace", "Delete"]}
            fitView
            minZoom={0.2}
            maxZoom={2}
            multiSelectionKeyCode="Shift"
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
      {nodeMenu && <div ref={nodeMenuElement} tabIndex={-1} className="studio-node-menu" role="menu" aria-label={t("Add workflow module", "添加工作流模块")} style={{ left: Math.max(8, Math.min(nodeMenu.x, window.innerWidth - 268)), top: Math.max(8, Math.min(nodeMenu.y, window.innerHeight - 390)) }} onKeyDown={event => {
        const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
        const current = buttons.indexOf(window.document.activeElement as HTMLButtonElement);
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault(); buttons[event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowUp" ? -1 : 1) + buttons.length) % buttons.length]?.focus();
        }
        if (event.key === "Escape" || event.key === "Tab") { event.preventDefault(); setNodeMenu(null); canvasElement.current?.focus(); }
      }}>
        <strong>{t("Add module", "添加模块")}</strong>
        {[
          { title: t("Data & flow", "数据与流程"), types: ["transform", "condition", "wait", "approval"] },
          { title: t("Models & tools", "模型与工具"), types: ["agent", "capability", "connector", "command"] },
        ].map(group => <div role="group" aria-label={group.title} key={group.title}><small>{group.title}</small>{group.types.map(value => {
          const type = value as WorkflowStepType;
          return <button key={type} role="menuitem" disabled={paramsPending || !stepAvailable(type)} onClick={() => addStep(type, nodeMenu.position)}>{stepTitle(type)}{!stepAvailable(type) && <small>{t("Unsupported", "不支持")}</small>}</button>;
        })}</div>)}
      </div>}
      <details open={!!run} className="studio-workflow-result">
        <summary>
          {t("Execution / Evidence", "执行 / 证据")}
          {run && ` · ${run.state}`}
        </summary>
        {run && (
          <>
            <strong>{run.run_id}</strong>
            <span>runtime-service · NOT_PHYSICAL_VERIFICATION</span>
            <button
              disabled={busy}
              onClick={() => void action(() => inspect(run.run_id, runGraph))}
            >
              {t("Inspect original", "查询原始记录")}
            </button>
            {["running", "waiting_approval", "unknown"].includes(run.state) && (
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await mutate(
                      `/api/v1/workflow/runs/${encodeURIComponent(run.run_id)}/action`,
                      { action: "cancel" },
                    );
                    await inspect(run.run_id, runGraph);
                    await reload();
                  })
                }
              >
                {t("Cancel", "取消")}
              </button>
            )}
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await mutate(
                    `/api/v1/workflow/runs/${encodeURIComponent(run.run_id)}/action`,
                    { action: "resume" },
                  );
                  await inspect(run.run_id, runGraph);
                  await reload();
                })
              }
            >
              {t("Reconcile / Resume original", "核对 / 恢复原始记录")}
            </button>
            {run.state === "waiting_approval" &&
              Object.entries(run.step_states)
                .filter(([, state]) => state === "waiting_approval")
                .map(([stepId]) => (
                  <button
                    key={stepId}
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        await humanMutation(
                          `/api/v1/workflow/runs/${encodeURIComponent(run.run_id)}/action`,
                          {
                            action: "approve",
                            step_id: stepId,
                            definition_digest: run.definition_digest,
                          },
                        );
                        await inspect(run.run_id, runGraph);
                        await reload();
                      })
                    }
                  >
                    {t("Approve original step", "审批原始节点")} · {stepId}
                  </button>
                ))}
            <ul className="studio-workflow-step-states">
              {Object.entries(run.step_states).map(([id, state]) => (
                <li key={id}>
                  <strong>{id}</strong>
                  <span>{state}</span>
                </li>
              ))}
            </ul>
            <details>
              <summary>{t("Raw record / events", "原始记录 / 事件")}</summary>
              <pre>
                {JSON.stringify(
                  { run, events, step_bindings: stepBindings },
                  null,
                  2,
                )}
              </pre>
            </details>
          </>
        )}
      </details>
    </section>
  );
}
