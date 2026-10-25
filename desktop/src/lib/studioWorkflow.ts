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
};
const identifier = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
export const runnableStep = (step: WorkflowStep) =>
  ["transform", "wait", "condition", "approval"].includes(step.step_type) &&
  !step.action &&
  !step.condition &&
  !step.compensation;
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
export function workflowDraft(value: unknown): WorkflowDraft {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid workflow draft");
  const data = value as Record<string, unknown>;
  if (!Object.hasOwn(data, "definition"))
    return { definition: workflowDefinition(data), positions: {} };
  if (
    data.schemaVersion !== 1 ||
    Object.keys(data).some(
      (key) => !["schemaVersion", "definition", "positions"].includes(key),
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
  return { definition, positions };
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
