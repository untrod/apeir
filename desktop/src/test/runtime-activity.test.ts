import { describe, expect, it } from "vitest";

import { runtimeActivityLabel, summarizeRuntimeActivity } from "../lib/runtimeActivity";

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

  it("distinguishes tool completion from independent verification and unknown outcomes", () => {
    expect(runtimeActivityLabel({ event_type: "tool.completed", payload: { tool: "read_file", ok: true } })).toBe("read_file completed");
    const summary = summarizeRuntimeActivity([
      { event_type: "tool.completed", payload: { tool: "a", ok: true } },
      { event_type: "tool.completed", payload: { tool: "b", ok: false } },
      { event_type: "tool.completed", payload: { tool: "c" } },
    ]);
    expect(summary.completedTools).toBe(1);
    expect(summary.failedTools).toBe(1);
    expect(summary.unknownTools).toBe(1);
    expect(summary.current).toBe("c UNKNOWN");
    expect(runtimeActivityLabel({ event_type: "verification.completed" })).toBe("Verification UNKNOWN");
  });

  it("shows actual model failures and approval waits instead of stale running labels", () => {
    const events = [{ event_type: "model.invocation.failed", payload: { model_id: "cloud/vendor/model", iteration: 2 } }];
    expect(summarizeRuntimeActivity(events).current).toBe("cloud/vendor/model · iteration 2 failed");
    expect(summarizeRuntimeActivity([...events, { event_type: "approval.requested", payload: {} }]).current).toBe("Waiting for approval");
  });
});
