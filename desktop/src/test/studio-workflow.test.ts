import { describe, expect, it } from "vitest";
import {
  arrangeWorkflow,
  initialWorkflow,
  runnableStep,
  workflowDefinition,
  workflowDraft,
} from "../lib/studioWorkflow";

describe("canonical workflow graph and portable drafts", () => {
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
