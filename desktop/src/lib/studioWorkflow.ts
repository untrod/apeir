/** Canonical WorkflowDefinition JSON. Canvas coordinates never affect execution. */
export const workflowStepTypes = [
  "agent",
  "capability",
  "connector",
  "command",
  "approval",
  "condition",
  "wait",
  "transform",
] as const;
export type WorkflowStepType = (typeof workflowStepTypes)[number];
export type WorkflowDataReference =
  | { source: "inputs"; pointer?: string }
  | { source: "step"; step_id: string; pointer?: string };
export type WorkflowDataBindings = {
  schema_version: 1;
  inputs?: Record<string, WorkflowDataReference>;
  inputs_schema?: Record<string, unknown>;
  outputs_schema?: Record<string, unknown>;
};
export type WorkflowStep = {
  step_id: string;
  step_type: WorkflowStepType;
  action?: string;
  depends_on?: string[];
  condition?: string;
  retries?: number;
  timeout_seconds?: number;
  approval_required?: boolean;
  compensation?: string;
  params?: Record<string, unknown>;
  data_bindings?: WorkflowDataBindings;
};
export type WorkflowDefinition = {
  workflow_id: string;
  version: string;
  trigger: "manual" | "schedule" | "event" | "webhook";
  steps: WorkflowStep[];
  inputs_schema?: Record<string, unknown>;
  outputs_schema?: Record<string, unknown>;
  audit_metadata?: Record<string, unknown>;
};
export type WorkflowCanvas = Record<string, { x: number; y: number }>;
export type WorkflowDraft = {
  definition: WorkflowDefinition;
  positions: WorkflowCanvas;
  /** Optional private draft-file content; never part of a layout or execution definition. */
  inputText?: string;
};
const identifier = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
export const modelWorkflowStep = (step: WorkflowStep) =>
  step.step_type === "agent" && step.action === "model.invoke";
export const runnableStep = (step: WorkflowStep) => {
  if (step.condition || step.compensation) return false;
  if (modelWorkflowStep(step)) {
    const p = step.params ?? {};
    return (
      step.approval_required === true &&
      !step.retries &&
      typeof p.model_id === "string" &&
      !!p.model_id.trim() &&
      typeof p.instruction === "string" &&
      !!p.instruction.trim() &&
      Number.isInteger(p.max_tokens) &&
      Number(p.max_tokens) > 0 &&
      Number(p.max_tokens) <= 32768 &&
      typeof p.max_cost_usd === "number" &&
      Number.isFinite(p.max_cost_usd) &&
      p.max_cost_usd >= 0 &&
      Object.keys(step.data_bindings?.inputs ?? {}).every(
        (key) => key === "input",
      )
    );
  }
  return (
    ["transform", "wait", "condition", "approval"].includes(step.step_type) &&
    !step.action
  );
};
export function workflowDefinition(value: unknown): WorkflowDefinition {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("WorkflowDefinition must be an object");
  const d = value as WorkflowDefinition;
  if (new TextEncoder().encode(JSON.stringify(value)).length > 96 * 1024)
    throw new Error("WorkflowDefinition exceeds 96 KiB");
  if (
    Object.keys(d).some(
      (key) =>
        ![
          "workflow_id",
          "version",
          "trigger",
          "steps",
          "inputs_schema",
          "outputs_schema",
          "audit_metadata",
        ].includes(key),
    )
  )
    throw new Error("Unknown definition field");
  if (
    typeof d.workflow_id !== "string" ||
    typeof d.version !== "string" ||
    !identifier.test(d.workflow_id) ||
    !identifier.test(d.version) ||
    !["manual", "schedule", "event", "webhook"].includes(d.trigger)
  )
    throw new Error("Invalid workflow identity or trigger");
  if (!Array.isArray(d.steps) || !d.steps.length || d.steps.length > 64)
    throw new Error("Workflow requires 1–64 steps");
  const ids = new Set<string>();
  for (const step of d.steps) {
    if (
      !step ||
      typeof step.step_id !== "string" ||
      !identifier.test(step.step_id) ||
      ids.has(step.step_id) ||
      !workflowStepTypes.includes(step.step_type)
    )
      throw new Error("Invalid or duplicate step ID/type");
    if (
      Object.keys(step).some(
        (key) =>
          ![
            "step_id",
            "step_type",
            "action",
            "depends_on",
            "condition",
            "retries",
            "timeout_seconds",
            "approval_required",
            "compensation",
            "params",
            "data_bindings",
          ].includes(key),
      )
    )
      throw new Error("Unknown step field");
    if (
      step.depends_on !== undefined &&
      (!Array.isArray(step.depends_on) ||
        step.depends_on.some((id) => typeof id !== "string") ||
        new Set(step.depends_on).size !== step.depends_on.length)
    )
      throw new Error("Invalid dependencies");
    if (
      step.params !== undefined &&
      (!step.params ||
        typeof step.params !== "object" ||
        Array.isArray(step.params))
    )
      throw new Error("Step params must be an object");
    if (step.data_bindings !== undefined) validateDataBindings(step);
    ids.add(step.step_id);
  }
  const active = new Set<string>(),
    visited = new Set<string>();
  const visit = (id: string) => {
    if (!ids.has(id)) throw new Error(`Missing dependency: ${id}`);
    if (active.has(id)) throw new Error("Workflow contains a cycle");
    if (visited.has(id)) return;
    active.add(id);
    d.steps.find((step) => step.step_id === id)!.depends_on?.forEach(visit);
    active.delete(id);
    visited.add(id);
  };
  ids.forEach(visit);
  return structuredClone(d);
}
function validateDataBindings(step: WorkflowStep) {
  const data = step.data_bindings!;
  const object = (value: unknown): value is Record<string, unknown> =>
    !!value && typeof value === "object" && !Array.isArray(value);
  if (
    !object(data) ||
    data.schema_version !== 1 ||
    Object.keys(data).some(
      (key) =>
        ![
          "schema_version",
          "inputs",
          "inputs_schema",
          "outputs_schema",
        ].includes(key),
    )
  )
    throw new Error("Unsupported data binding contract");
  for (const key of ["inputs_schema", "outputs_schema"] as const)
    if (data[key] !== undefined && !object(data[key]))
      throw new Error("Step schema must be an object");
  if (data.inputs !== undefined && !object(data.inputs))
    throw new Error("Invalid data binding targets");
  const refs = data.inputs ?? {};
  if (!object(refs) || Object.keys(refs).length > 64)
    throw new Error("Invalid data binding targets");
  for (const [target, ref] of Object.entries(refs)) {
    if (
      !/^[A-Za-z][A-Za-z0-9_.-]{0,127}$/.test(target) ||
      Object.hasOwn(step.params ?? {}, target) ||
      !object(ref)
    )
      throw new Error("Invalid or conflicting data binding target");
    if (ref.source !== "inputs" && ref.source !== "step")
      throw new Error("Invalid data source");
    const allowed =
      ref.source === "step"
        ? ["source", "step_id", "pointer"]
        : ["source", "pointer"];
    if (Object.keys(ref).some((key) => !allowed.includes(key)))
      throw new Error("Unknown data source field");
    if (ref.source === "step" && !(step.depends_on ?? []).includes(ref.step_id))
      throw new Error("Data source must be a declared dependency");
    const pointer = ref.pointer === undefined ? "" : ref.pointer;
    if (
      typeof pointer !== "string" ||
      pointer.length > 1024 ||
      (pointer !== "" && !pointer.startsWith("/")) ||
      /~(?![01])/.test(pointer)
    )
      throw new Error("Invalid data pointer");
    const parts = pointer === "" ? [] : pointer.slice(1).split("/");
    if (parts.length > 32 || parts.some((part) => part.startsWith("_")))
      throw new Error("Reserved or excessive data path");
  }
}
export function workflowDraft(value: unknown): WorkflowDraft {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid workflow draft");
  const data = value as Record<string, unknown>;
  if (!Object.hasOwn(data, "definition"))
    return { definition: workflowDefinition(data), positions: {} };
  if (
    data.schemaVersion !== 1 ||
    Object.keys(data).some(
      (key) => !["schemaVersion", "definition", "positions", "inputText"].includes(key),
    )
  )
    throw new Error("Unsupported draft schema");
  const definition = workflowDefinition(data.definition),
    positions: WorkflowCanvas = {};
  if (
    !data.positions ||
    typeof data.positions !== "object" ||
    Array.isArray(data.positions)
  )
    throw new Error("Invalid canvas positions");
  for (const [id, pos] of Object.entries(data.positions)) {
    const p = pos as { x: number; y: number };
    if (
      !definition.steps.some((step) => step.step_id === id) ||
      !p ||
      Object.keys(p).some((key) => !["x", "y"].includes(key)) ||
      ![p.x, p.y].every(
        (n) =>
          typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= 100000,
      )
    )
      throw new Error("Invalid canvas position");
    positions[id] = { x: p.x, y: p.y };
  }
  if (data.inputText !== undefined && (typeof data.inputText !== "string" || new TextEncoder().encode(data.inputText).length > 32 * 1024))
    throw new Error("Invalid or oversized draft inputs");
  return { definition, positions, ...(data.inputText === undefined ? {} : { inputText: data.inputText as string }) };
}
export function arrangeWorkflow(
  definition: WorkflowDefinition,
): WorkflowCanvas {
  const positions: WorkflowCanvas = {},
    rows = new Map<number, number>();
  const depths = new Map<string, number>();
  const depth = (id: string): number => {
    if (depths.has(id)) return depths.get(id)!;
    const deps =
      definition.steps.find((step) => step.step_id === id)!.depends_on || [];
    const value = deps.length ? 1 + Math.max(...deps.map(depth)) : 0;
    depths.set(id, value);
    return value;
  };
  workflowDefinition(definition);
  definition.steps.forEach((step) => {
    const column = depth(step.step_id),
      row = rows.get(column) || 0;
    rows.set(column, row + 1);
    positions[step.step_id] = { x: column * 240, y: row * 120 };
  });
  return positions;
}
export const initialWorkflow = (): WorkflowDraft => ({
  definition: {
    workflow_id: "studio.workflow",
    version: "1.0.0",
    trigger: "manual",
    steps: [
      {
        step_id: "transform",
        step_type: "transform",
        params: { value: "Hello APEIR" },
      },
    ],
  },
  positions: {},
});

/** Display comparison only; execution admission and digests stay with Runtime. */
export function sameWorkflowDefinition(a: WorkflowDefinition, b: WorkflowDefinition): boolean {
  const normalize = (d: WorkflowDefinition) => ({
    workflow_id: d.workflow_id, version: d.version, trigger: d.trigger,
    steps: d.steps.map(s => ({ action: "", depends_on: [], condition: "", retries: 0, timeout_seconds: 60, approval_required: false, compensation: "", params: {}, ...s })),
    inputs_schema: d.inputs_schema || {}, outputs_schema: d.outputs_schema || {}, audit_metadata: d.audit_metadata || {},
  });
  const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, stable(v)])) : value;
  return JSON.stringify(stable(normalize(a))) === JSON.stringify(stable(normalize(b)));
}

export const WORKFLOW_TEMPLATES = [
  { id: "approval-review", en: "Review a request", zh: "审批一份请求", descriptionEn: "Collect a brief, request human approval and keep the result. No model needed.", descriptionZh: "填写需求、人工审批并保存结果，无需模型。" },
  { id: "model-review", en: "Draft and review", zh: "模型分析与复核", descriptionEn: "One model proposes a plan; another reviews it. Select models and approve each call.", descriptionZh: "一个模型提出方案，另一个复核；模型选择和每次调用均需确认。" },
] as const;

/** Configuration over supported Runtime handlers; choosing a template executes nothing. */
export function createWorkflowTemplate(id: typeof WORKFLOW_TEMPLATES[number]["id"]): WorkflowDraft {
  const inputs_schema = { type: "object", properties: { request: { type: "string", title: "Request / 需求", minLength: 1, maxLength: 16000 } }, required: ["request"], additionalProperties: false };
  let definition: WorkflowDefinition;
  if (id === "approval-review") {
    definition = { workflow_id: "studio.request-review", version: "1.0.0", trigger: "manual", inputs_schema, steps: [
      { step_id: "request", step_type: "transform", data_bindings: { schema_version: 1, inputs: { value: { source: "inputs", pointer: "/request" } } } },
      { step_id: "approval", step_type: "approval", depends_on: ["request"] },
      { step_id: "result", step_type: "transform", depends_on: ["approval", "request"], data_bindings: { schema_version: 1, inputs: { value: { source: "step", step_id: "request", pointer: "/value" } } } },
    ] };
  } else if (id === "model-review") {
    const model = (step_id: string, instruction: string): WorkflowStep => ({ step_id, step_type: "agent", action: "model.invoke", approval_required: true, params: { model_id: "", instruction, max_tokens: 768, max_cost_usd: 0.01 } });
    definition = { workflow_id: "studio.model-review", version: "1.0.0", trigger: "manual", inputs_schema, steps: [
      { ...model("analysis", "Analyze the supplied request. Propose a concise plan, assumptions and checks. Do not claim to have read files or executed tools."), data_bindings: { schema_version: 1, inputs: { input: { source: "inputs", pointer: "/request" } } } },
      { ...model("review", "Review the supplied analysis. Identify mistakes, risks and missing checks. Return a concise review; do not execute any operation."), depends_on: ["analysis"], data_bindings: { schema_version: 1, inputs: { input: { source: "step", step_id: "analysis", pointer: "/content" } } } },
    ] };
  } else throw new Error("Unknown Workflow template");
  workflowDefinition(definition);
  return { definition, positions: arrangeWorkflow(definition) };
}
