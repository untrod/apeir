export interface NousClientOptions { baseUrl?: string; token?: string; }
export type RuntimeResponse<T = unknown> = {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string; details?: Record<string, unknown> };
};
export type EventSubscription = { close(): void; cursor(): number };

export class NousClient {
  private readonly baseUrl: string;
  private readonly token: string;

  constructor(options: NousClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8770").replace(/\/$/, "");
    this.token = options.token ?? "";
  }

  status() { return this.request("GET", "/api/v1/status"); }
  chat(text: string, workspaceId = "default", conversationId = "") {
    return this.request("POST", "/api/chat", { text, workspace_id: workspaceId, conversation_id: conversationId });
  }
  run(capabilityId: string, params: Record<string, unknown> = {}) {
    return this.request("POST", "/api/v1/capabilities/run", { capability_id: capabilityId, params });
  }
  workflow(workflowId: string, inputs: Record<string, unknown> = {}, version = "1.0.0") {
    return this.request("POST", "/api/workflow/run", { workflow_id: workflowId, version, inputs });
  }
  listRuns(limit = 20) {
    return this.request("GET", `/api/runtime/runs?limit=${Math.max(1, Math.min(limit, 200))}`);
  }
  runEvents(runId: string, afterSequence = 0, limit = 200) {
    const run = encodeURIComponent(runId);
    const after = Math.max(0, afterSequence);
    const bounded = Math.max(1, Math.min(limit, 1000));
    return this.request("GET", `/api/runtime/runs/${run}/events?after_sequence=${after}&limit=${bounded}`);
  }
  events(
    runId: string,
    onEvent: (event: unknown) => void,
    options: { intervalMs?: number; afterSequence?: number } = {},
  ): EventSubscription {
    let active = true;
    let cursor = Math.max(0, options.afterSequence ?? 0);
    const interval = Math.max(250, options.intervalMs ?? 1000);
    const poll = async () => {
      if (!active) return;
      try {
        const response = await this.runEvents(runId, cursor) as RuntimeResponse<{
          events: Array<Record<string, unknown>>;
          next_after_sequence: number;
        }>;
        for (const event of response.data?.events ?? []) onEvent(event);
        cursor = response.data?.next_after_sequence ?? cursor;
      } catch {
        // Preserve the cursor and retry after transient disconnects.
      } finally {
        if (active) setTimeout(poll, interval);
      }
    };
    void poll();
    return { close: () => { active = false; }, cursor: () => cursor };
  }

  private async request(method: string, path: string, body?: unknown): Promise<RuntimeResponse> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const payload = await response.json() as RuntimeResponse;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error?.message ?? `HTTP ${response.status}`);
    }
    return payload;
  }
}