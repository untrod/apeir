import { describe, expect, it } from "vitest";

import { summarizeRuntimeActivity } from "../lib/runtimeActivity";

describe("runtime activity summary", () => {
  it("summarizes model, tool, artifact, and usage progress", () => {
    const summary = summarizeRuntimeActivity([
      { event_type: "plan.created", payload: {} },
      { event_type: "model.invocation.completed", payload: { iteration: 2, usage: { total_tokens: 120 } } },
      { event_type: "tool.completed", payload: { tool: "write_file", ok: true } },
      { event_type: "artifact.created", payload: { path: "project/main.py" } },
    ]);

    expect(summary.iteration).toBe(2);
    expect(summary.completedTools).toBe(1);
    expect(summary.artifacts).toBe(1);
    expect(summary.tokens).toBe(120);
    expect(summary.current).toContain("project/main.py");
  });
});
