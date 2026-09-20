export interface ActivityEvent {
  event_type?: string;
  payload?: Record<string, unknown>;
}

export interface RuntimeActivitySummary {
  current: string;
  recent: string[];
  iteration: number;
  completedTools: number;
  failedTools: number;
  artifacts: number;
  tokens: number;
}

export function runtimeActivityLabel(event: ActivityEvent): string {
  const payload = event.payload || {};
  switch (event.event_type) {
    case "intent.resolved": return "Understood the request";
    case "plan.created": return "Prepared the execution plan";
    case "collaboration.started": return `Scheduled ${Number(payload.lane_count || 0)} work lanes`;
    case "manager.completed": return "Manager prepared the delivery contract";
    case "model.lane.started": return `${String(payload.lane_id || "Worker")} started`;
    case "model.lane.completed": return `${String(payload.lane_id || "Worker")} completed`;
    case "model.invocation.started": return `Model iteration ${Number(payload.iteration || 0)} running`;
    case "model.invocation.completed": return `Model iteration ${Number(payload.iteration || 0)} completed`;
    case "execution.budget.configured": return `Execution budget: ${Number(payload.max_model_iterations || 0)} iterations`;
    case "tool.started": return `Using ${String(payload.tool || "workspace tool")}`;
    case "tool.completed": return `${String(payload.tool || "Tool")} ${payload.ok ? "verified" : "failed"}`;
    case "artifact.created": return `Created ${String(payload.path || payload.artifact_id || "artifact")}`;
    case "review.started": return "Reviewer checking the result";
    case "review.completed": return payload.approved === false ? "Review found gaps" : "Review completed";
    case "verification.completed": return payload.accepted ? "Verification passed" : "Verification needs attention";
    default: return String(event.event_type || "Working");
  }
}

export function summarizeRuntimeActivity(events: ActivityEvent[]): RuntimeActivitySummary {
  const visibleTypes = new Set([
    "intent.resolved", "plan.created", "collaboration.started", "manager.completed",
    "model.lane.started", "model.lane.completed", "model.invocation.started",
    "model.invocation.completed", "execution.budget.configured", "tool.started", "tool.completed", "artifact.created",
    "review.started", "review.completed", "verification.completed",
  ]);
  const visible = events.filter((event) => visibleTypes.has(String(event.event_type || "")));
  const recent = visible.slice(-6).map(runtimeActivityLabel);
  let iteration = 0;
  let completedTools = 0;
  let failedTools = 0;
  let artifacts = 0;
  let tokens = 0;
  for (const event of events) {
    const payload = event.payload || {};
    iteration = Math.max(iteration, Number(payload.iteration || 0));
    if (event.event_type === "tool.completed") {
      if (payload.ok) completedTools += 1;
      else failedTools += 1;
    }
    if (event.event_type === "artifact.created") artifacts += 1;
    const usage = payload.usage;
    if (usage && typeof usage === "object") {
      const values = usage as Record<string, unknown>;
      tokens += Number(values.total_tokens || values.total || 0);
    }
  }
  return {
    current: recent[recent.length - 1] || "Understanding the request",
    recent,
    iteration,
    completedTools,
    failedTools,
    artifacts,
    tokens,
  };
}
