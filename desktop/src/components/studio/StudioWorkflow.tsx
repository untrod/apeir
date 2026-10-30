import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
} from "../../lib/api";
import {
  arrangeWorkflow,
  initialWorkflow,
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
  const [bindingsText, setBindingsText] = useState("");
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
      commit({ ...current, definition });
    });
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
          <strong>{item.step_id}</strong>
          <span>
            {item.step_type.toUpperCase()} ·{" "}
            {(graphMatchesRun && run?.step_states[item.step_id]) ||
              (runnableStep(item) ? "READY" : "UNSUPPORTED")}
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
            draft.definition.steps.some((item) => !runnableStep(item))
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
                disabled={[
                  "agent",
                  "capability",
                  "connector",
                  "command",
                ].includes(type)}
              >
                {type.toUpperCase()}
                {["agent", "capability", "connector", "command"].includes(type)
                  ? " · UNSUPPORTED"
                  : ""}
              </option>
            ))}
          </select>
          <button
            disabled={paramsPending}
            onClick={() =>
              edit((d) => ({
                ...d,
                steps: [
                  ...d.steps,
                  {
                    step_id: `step-${crypto.randomUUID().slice(0, 8)}`,
                    step_type: kind,
                    params: kind === "transform" ? { value: null } : {},
                  },
                ],
              }))
            }
          >
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
              <strong>{step.step_id}</strong>
              <label>
                {t("Parameters", "参数")}
                <textarea
                  aria-label="Step parameters"
                  value={paramsText}
                  maxLength={32768}
                  onChange={(e) => {
                    setParamsText(e.target.value);
                    setDirty(true);
                  }}
                />
              </label>
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
                                updated.data_bindings = JSON.parse(bindingsText);
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
        </aside>
        <div className="studio-workflow-canvas">
          <ReactFlow
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
