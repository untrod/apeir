import { describe, expect, it } from "vitest";
import {
  arrangeWorkflow,
  initialWorkflow,
  runnableStep,
  workflowDefinition,
  workflowDraft,
} from "../lib/studioWorkflow";

describe("canonical workflow graph and portable drafts", () => {
  it("requires explicit model selection, budgets and independent approval", () => {
    const step = {
      step_id: "model",
      step_type: "agent" as const,
      action: "model.invoke",
      approval_required: true,
      params: {
        model_id: "provider/registered-id",
        instruction: "Review the input",
        max_tokens: 512,
        max_cost_usd: 0.01,
      },
    };
    expect(runnableStep(step)).toBe(true);
    expect(runnableStep({ ...step, approval_required: false })).toBe(false);
    expect(
      runnableStep({ ...step, params: { ...step.params, model_id: "" } }),
    ).toBe(false);
    expect(
      runnableStep({ ...step, params: { ...step.params, max_cost_usd: NaN } }),
    ).toBe(false);
    expect(runnableStep({ ...step, retries: 1 })).toBe(false);
    expect(
      runnableStep({
        ...step,
        data_bindings: {
          schema_version: 1,
          inputs: {
            max_cost_usd: { source: "inputs", pointer: "/untrusted" },
          },
        },
      }),
    ).toBe(false);
    const draft = initialWorkflow();
    draft.definition.steps.push(step);
    expect(workflowDefinition(draft.definition).steps[1]).toEqual(step);
  });
  it("exports the original definition without coordinates or authority", () => {
    const draft = initialWorkflow();
    draft.definition.steps.push({
      step_id: "end",
      step_type: "wait",
      depends_on: ["transform"],
      params: {},
    });
    draft.positions = arrangeWorkflow(draft.definition);
    expect(
      workflowDraft(JSON.parse(JSON.stringify({ schemaVersion: 1, ...draft }))),
    ).toEqual(draft);
    expect(JSON.stringify(workflowDefinition(draft.definition))).not.toContain(
      '"positions"',
    );
    expect(draft.positions.end.x).toBeGreaterThan(draft.positions.transform.x);
  });
  it("preserves host-specific semantics without claiming a handler", () => {
    const original = initialWorkflow().definition;
    original.steps[0] = {
      step_id: "host",
      step_type: "command",
      action: "existing.profile",
      compensation: "original-compensation",
      params: { profile: "tests" },
    };
    expect(workflowDefinition(original)).toEqual(original);
    expect(runnableStep(original.steps[0])).toBe(false);
    expect(runnableStep({ step_id: "a", step_type: "wait" })).toBe(true);
    expect(
      runnableStep({
        step_id: "a",
        step_type: "transform",
        condition: "unsupported-expression",
      }),
    ).toBe(false);
  });
  it("rejects missing dependencies, cycles, duplicates and executable canvas data", () => {
    const def = initialWorkflow().definition;
    expect(() =>
      workflowDefinition({ ...def, steps: [...def.steps, ...def.steps] }),
    ).toThrow(/duplicate/);
    expect(() =>
      workflowDefinition({
        ...def,
        steps: [{ ...def.steps[0], depends_on: ["missing"] }],
      }),
    ).toThrow(/Missing/);
    expect(() =>
      workflowDefinition({
        ...def,
        steps: [{ ...def.steps[0], depends_on: ["transform"] }],
      }),
    ).toThrow(/cycle/);
    expect(() =>
      workflowDraft({
        schemaVersion: 1,
        definition: def,
        positions: {},
        javascript: "ignored?",
      }),
    ).toThrow(/schema/);
    expect(() =>
      workflowDraft({
        schemaVersion: 1,
        definition: def,
        positions: { transform: { x: 0, y: Infinity } },
      }),
    ).toThrow(/position/);
    expect(() =>
      workflowDefinition({ ...def, workflow_id: undefined }),
    ).toThrow(/identity/);
  });
  it("lays out a shared dependency graph without exponential traversal", () => {
    const def = initialWorkflow().definition;
    for (let i = 0; i < 30; i++)
      def.steps.push({
        step_id: `s${i}`,
        step_type: "transform",
        depends_on: i ? [`s${i - 1}`, "transform"] : ["transform"],
      });
    expect(Object.keys(arrangeWorkflow(def))).toHaveLength(31);
  });
  it("keeps versioned data references and schemas outside canvas state", () => {
    const definition = initialWorkflow().definition;
    definition.steps.push({
      step_id: "consumer",
      step_type: "transform",
      depends_on: ["transform"],
      params: {},
      data_bindings: {
        schema_version: 1,
        inputs: {
          value: { source: "step", step_id: "transform", pointer: "/value" },
        },
        inputs_schema: { properties: { value: { type: "string" } } },
      },
    });
    const restored = workflowDraft(
      JSON.parse(
        JSON.stringify({
          schemaVersion: 1,
          definition,
          positions: arrangeWorkflow(definition),
        }),
      ),
    );
    expect(restored.definition).toEqual(definition);
    expect(runnableStep(restored.definition.steps[1])).toBe(true);
    expect(workflowDefinition(restored.definition)).not.toHaveProperty(
      "positions",
    );
    expect(() =>
      workflowDefinition({
        ...definition,
        steps: [
          definition.steps[0],
          { ...definition.steps[1], depends_on: [] },
        ],
      }),
    ).toThrow(/declared dependency/);
  });
  it.each([
    { schema_version: 2 },
    { schema_version: true },
    { schema_version: 1, javascript: "run()" },
    { schema_version: 1, inputs: null },
    {
      schema_version: 1,
      inputs: { value: { source: "inputs", pointer: null } },
    },
    {
      schema_version: 1,
      inputs: { value: { source: "inputs", pointer: "/bad~2" } },
    },
    {
      schema_version: 1,
      inputs: { value: { source: "inputs", pointer: "/_approved_steps" } },
    },
    {
      schema_version: 1,
      inputs: { value: { source: "inputs", approval: true } },
    },
  ])(
    "rejects unsupported or authority-shaped data contracts",
    (data_bindings) => {
      const definition = initialWorkflow().definition;
      expect(() =>
        workflowDefinition({
          ...definition,
          steps: [{ ...definition.steps[0], params: {}, data_bindings }],
        }),
      ).toThrow();
    },
  );
});

describe("task workflow templates and original graph identity", () => {
  it("ignores persisted object key order while keeping request and array identities distinct", async () => {
    const { sameWorkflowInputs, workflowRequestFingerprint } = await import("../lib/studioWorkflow");
    const input = { z: { second: 2, first: 1 }, a: [1, 2] };
    const restored = { a: [1, 2], z: { first: 1, second: 2 } };
    expect(sameWorkflowInputs(input, restored)).toBe(true);
    expect(sameWorkflowInputs(input, { ...restored, a: [2, 1] })).toBe(false);
    expect(workflowRequestFingerprint(initialWorkflow().definition, input)).toBe(workflowRequestFingerprint(initialWorkflow().definition, restored));
    expect(workflowRequestFingerprint(initialWorkflow().definition, input)).not.toBe(workflowRequestFingerprint(initialWorkflow().definition, { ...restored, a: [2, 1] }));
  });
  it("round-trips private input drafts while preserving legacy files and execution definitions", () => {
    const original = initialWorkflow();
    const inputText = '{"request":"Review this change"}';
    const saved = workflowDraft({ schemaVersion: 1, ...original, inputText });
    expect(saved.inputText).toBe(inputText);
    expect(saved.definition).toEqual(original.definition);
    expect(saved.positions).toEqual(original.positions);
    expect(workflowDraft({ schemaVersion: 1, ...original }).inputText).toBeUndefined();
    expect(() => workflowDraft({ schemaVersion: 1, ...original, inputText: "x".repeat(32769) })).toThrow(/inputs/);
    expect(() => workflowDraft({ schemaVersion: 1, ...original, inputText: { approval: true } })).toThrow(/inputs/);
  });
  it("keeps optional serialization defaults equivalent without hiding a changed operation", async () => {
    const { sameWorkflowDefinition } = await import("../lib/studioWorkflow");
    const d = initialWorkflow().definition;
    const normalized = { ...d, inputs_schema: {}, outputs_schema: {}, audit_metadata: {}, steps: d.steps.map(s => ({ action: "", condition: "", compensation: "", retries: 0, timeout_seconds: 60, depends_on: [], approval_required: false, ...s })) };
    expect(sameWorkflowDefinition(d, normalized)).toBe(true);
    expect(sameWorkflowDefinition(d, { ...normalized, steps: [{ ...normalized.steps[0], params: { value: "other effect" } }] })).toBe(false);
    expect(sameWorkflowDefinition(d, { ...normalized, steps: [{ ...normalized.steps[0], approval_required: true }] })).toBe(false);
  });
  it("binds a reviewed request through the original approval step without credentials or execution code", async () => {
    const { createWorkflowTemplate } = await import("../lib/studioWorkflow");
    const d = createWorkflowTemplate("approval-review");
    expect(workflowDefinition(d.definition)).toEqual(d.definition);
    expect(d.definition.steps[1].step_type).toBe("approval");
    expect(d.definition.steps[2].depends_on).toContain(d.definition.steps[1].step_id);
    expect(d.definition.steps[2].data_bindings?.inputs?.value).toEqual({ source: "step", step_id: "request", pointer: "/value" });
    expect(d.definition.steps.every(runnableStep)).toBe(true);
    expect(JSON.stringify(d)).not.toMatch(/credential|authorization|command|javascript/);
  });
  it("requires two explicit model selections and original approvals before a review template is runnable", async () => {
    const { createWorkflowTemplate } = await import("../lib/studioWorkflow");
    const d = createWorkflowTemplate("model-review");
    expect(d.definition.steps.every(runnableStep)).toBe(false);
    expect(d.definition.steps.every(s => s.approval_required && s.action === "model.invoke" && !s.retries)).toBe(true);
    expect(d.definition.steps[1].data_bindings?.inputs?.input).toEqual({ source: "step", step_id: "analysis", pointer: "/content" });
    expect(JSON.stringify(d)).not.toMatch(/credential|api_key|host_shell/);
  });
});
