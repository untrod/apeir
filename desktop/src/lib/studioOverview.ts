/** Read-only projections. Missing measurements remain unknown. */
export function cacheShare(input: number | null, cached: number | null): number | null {
  if (input === null || cached === null || !Number.isSafeInteger(input) || !Number.isSafeInteger(cached) || input <= 0 || cached < 0 || cached > input) return null;
  return cached / input * 100;
}

export type WorkflowProgress = { run_id: string; workflow_id: string; state: string; step_counts?: Record<string, number> };
export function parseWorkflowProgress(raw: unknown): WorkflowProgress[] {
  if (!raw || typeof raw !== "object" || !("runs" in raw) || !Array.isArray(raw.runs) || raw.runs.length > 100) throw new Error("Workflow history unavailable.");
  return raw.runs.map((value: unknown) => {
    if (!value || typeof value !== "object") throw new Error("Invalid Workflow history.");
    const row = value as Record<string, unknown>;
    if (!["run_id", "workflow_id", "state"].every(key => typeof row[key] === "string" && (row[key] as string).length <= 256)) throw new Error("Invalid Workflow identity.");
    const result = { run_id: row.run_id as string, workflow_id: row.workflow_id as string, state: row.state as string };
    if (row.step_counts === undefined) return result; // Older Controllers still show original state.
    const counts = row.step_counts;
    if (!counts || typeof counts !== "object" || Array.isArray(counts)) throw new Error("Invalid Workflow progress.");
    const fields = ["total", "completed", "skipped", "failed", "unknown", "waiting_approval", "started", "running", "pending", "cancelled"];
    const parsed = counts as Record<string, number>;
    if (!fields.every(key => Number.isSafeInteger(parsed[key]) && parsed[key] >= 0) || fields.slice(1).reduce((sum, key) => sum + parsed[key], 0) !== parsed.total) throw new Error("Invalid Workflow progress counts.");
    return { ...result, step_counts: Object.fromEntries(fields.map(key => [key, parsed[key]])) };
  });
}
