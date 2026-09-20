/**
 * Nous Desktop API Bridge
 *
 * Thin TypeScript wrapper over the Nous Runtime HTTP API.
 * All state lives in the Runtime — this is a control surface.
 *
 * Base URL: http://localhost:8770 (configurable)
 */

import type { Conversation, Message } from "../store/types";

export interface RuntimeConfig {
  url: string;
  token: string;
}

export function describeRuntimeFailure(message: string): string {
  const value = message.trim();
  if (/HTTP 401|Unauthorized/i.test(value)) {
    return "Provider authentication failed. Update the Provider credential in Settings, then retry.";
  }
  if (/HTTP 402|Payment Required/i.test(value)) {
    return "The Provider rejected the request because the account has insufficient balance. Recharge this Provider account or select a model backed by a different Provider, then retry.";
  }
  if (/no model route satisfies hard constraints/i.test(value)) {
    return "No configured model can satisfy this request. Enable a compatible model in Models or Settings.";
  }
  if (/all safe model routes failed/i.test(value)) {
    return `All eligible model routes failed. ${value}`;
  }
  return value || "Runtime execution failed.";
}

// API Response Types

export interface ApiEnvelope<T = unknown> {
  ok: boolean;
  data?: T;
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

export interface RuntimeStatus {
  version: string;
  running: boolean;
  providers: number;
  capabilities: number;
  capability_availability?: { registered: number; available: number; unavailable: number };
  packs: number;
  devices: number;
  events: number;
  jobs_pending: number;
  demo_mode?: boolean;
  kernel?: {
    configured: boolean;
    connected: boolean;
    ready: boolean;
    state: string;
    runtime_version: string;
    journal_sequence: number;
    active_operations: number;
    error?: string;
  };
  execution_authorities?: {
    model_inference: string;
    local_effects: string;
  };
}

export interface CheckpointSummary {
  checkpoint_id: string;
  task_id: string;
  timestamp: string;
  kind: string;
  run_id: string;
  agent_id: string;
}

export interface CheckpointDiagnostics {
  status: "healthy" | "degraded" | "empty" | "unavailable";
  reason: string;
  workspace_available: boolean;
  database: {
    filename: string;
    exists: boolean;
    size_bytes: number;
  };
  integrity: {
    quick_check: "ok" | "failed" | "not_run";
    messages: string[];
    total: number;
    valid: number;
    invalid: number;
  };
  tasks: number;
  latest: CheckpointSummary[];
  invalid: {
    checkpoint_id: string;
    task_id: string;
    timestamp: string;
    reason: string;
  }[];
  retention: {
    policy: "keep_latest_per_task";
    keep_latest_per_task: number;
    candidate_count: number;
    protected_count: number;
    invalid_excluded: number;
    plan_digest: string;
    requires_governed_apply: boolean;
  };
}

export interface ModelView {
  id: string;
  model_id: string;
  display_name: string;
  provider_id: string;
  provider_kind: "openai" | "anthropic" | "local" | "custom";
  state: string;
  health: string;
  capabilities: string[];
  capability_scores: Record<string, number>;
  evaluation?: { overall_score?: number; error_rate?: number };
  recoverable: boolean;
  avg_latency_ms: number;
  cost_per_1k_tokens_usd: number;
  token_limit: number;
}

export interface TaskView {
  task_id: string;
  name: string;
  status: string;
  priority: string;
  model_id: string;
  duration: number | null;
  created_at: string;
}

export interface DeviceView {
  device_id: string;
  name: string;
  type: string;
  status: string;
  hardware?: string;
  address?: string;
  capabilities?: string[];
}

export interface AutomationView {
  id: string;
  name: string;
  trigger: string;
  schedule?: string;
  action: string;
  enabled: boolean;
  created_at: string;
}

export interface KnowledgeItem {
  id: string;
  title: string;
  category: string;
  format: string;
  summary: string;
  created_at: string;
}

export interface PermissionView {
  id: string;
  name: string;
  description: string;
  granted: boolean;
  risk: string;
}

export interface DashboardData {
  runtime: { version: string; running: boolean; demo_mode: boolean; kernel?: RuntimeStatus["kernel"] };
  models: { total: number; healthy: number };
  tasks: { total: number; running: number };
  devices: { total: number; online: number };
  memory: { used_pct: number; rss_mb: number; total_gb: number };
  providers: number;
  capabilities: number;
  events_total: number;
  jobs_pending: number;
}

// Config

let config: RuntimeConfig = { url: "http://localhost:8770", token: "" };

export function setConfig(value: RuntimeConfig) {
  config = value;
  sessionStorage.setItem("nous_server_url", value.url);
  sessionStorage.setItem("nous_server_token", value.token);
}

export function getConfig(): RuntimeConfig {
  return {
    url: sessionStorage.getItem("nous_server_url") || config.url,
    token: sessionStorage.getItem("nous_server_token") || config.token,
  };
}

// Core API Client

export class ApiError extends Error {
  code: string;
  details?: Record<string, unknown>;
  constructor(code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
  }
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const { url, token } = getConfig();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const response = await fetch(`${url}${path}`, { ...options, headers });
  const envelope = (await response.json()) as ApiEnvelope<T>;

  if (!response.ok || !envelope.ok) {
    throw new ApiError(
      envelope.error?.code || `HTTP_${response.status}`,
      envelope.error?.message || `Request failed with status ${response.status}`,
      envelope.error?.details,
    );
  }

  return envelope.data as T;
}

async function apiSafe<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<{ data: T | null; error: string | null }> {
  try {
    const data = await api<T>(path, options);
    return { data, error: null };
  } catch (e) {
    return { data: null, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function testConnection(): Promise<boolean> {
  const { error } = await apiSafe("/api/v1/status");
  return error === null;
}

// Named API Functions

// Dashboard
export const fetchDashboard = () => api<DashboardData>("/api/v1/dashboard");
export const fetchStatus = () => api<RuntimeStatus>("/api/v1/status");
export const fetchMemory = () => api<{ used_pct: number; rss_mb: number; total_gb: number }>("/api/v1/runtime/memory");

// Chat / Runtime
export const fetchConversations = () =>
  api<{ conversations: Conversation[] }>("/api/v1/conversations");

export const fetchConversation = (conversationId: string) =>
  api<Conversation & { messages: Message[] }>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
  );

export const runPrompt = (
  text: string,
  modelId?: string,
  conversationId?: string,
  agentMode: "agent" | "read_only" | "chat" = "agent",
  signal?: AbortSignal,
  requestId?: string,
) =>
  api<{
    conversation_id: string;
    message: string;
    status: string;
    trace_id?: string;
    run_id?: string;
    task_promoted?: boolean;
  }>(
    "/api/v1/chat",
    {
      method: "POST",
      signal,
      body: JSON.stringify({
        text,
        model_id: modelId,
        conversation_id: conversationId,
        workspace_id: "default",
        agent_mode: agentMode,
        request_id: requestId,
      }),
    },
  );

// Models
export const fetchModels = () =>
  api<{ models: ModelView[]; total_count: number; available_count: number }>("/api/v1/models");

export const modelAction = (action: string, modelId: string) =>
  api("/api/v1/models/action", {
    method: "POST",
    body: JSON.stringify({ action, model_id: modelId }),
  });

export interface ModelTestResult {
  model_id: string;
  selected_model_id: string;
  instance_id: string;
  request_id: string;
  response_id: string;
  healthy: boolean;
  latency_ms: number;
  response_preview?: string;
  finish_reason?: string;
  tokens_used?: number;
  execution?: {
    path?: string;
    operation_id?: string;
    workload_id?: string;
    backend?: string;
  };
  error?: string;
}

export const testModel = (modelId: string) =>
  api<ModelTestResult>("/api/v1/models/test", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  });


// Tasks
export const fetchTasks = (state?: string, limit = 50) => {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  params.set("limit", String(limit));
  return api<{ tasks: TaskView[]; total: number; running: number }>(`/api/v1/tasks?${params}`);
};

export const taskAction = (action: string, taskId: string) =>
  api("/api/v1/tasks/action", { method: "POST", body: JSON.stringify({ action, task_id: taskId }) });

// Devices
export const fetchDevices = () =>
  api<{ devices: DeviceView[]; total: number; online: number }>("/api/v1/devices");

export const scanDevices = () =>
  api<{ discovered: DeviceView[]; timestamp: number }>("/api/v1/devices/scan", { method: "POST" });

// Automations
export const fetchAutomations = () =>
  api<{ automations: AutomationView[]; total: number }>("/api/v1/automations");

export const addAutomation = (data: { name: string; trigger: string; schedule?: string; action: string }) =>
  api<AutomationView>("/api/v1/automations/add", { method: "POST", body: JSON.stringify(data) });

export const automationAction = (action: string, automationId: string) =>
  api("/api/v1/automations/action", { method: "POST", body: JSON.stringify({ action, automation_id: automationId }) });

// Knowledge
export const fetchKnowledge = (category?: string) => {
  const params = category && category !== "all" ? `?category=${category}` : "";
  return api<{ items: KnowledgeItem[]; total: number }>(`/api/v1/knowledge${params}`);
};

export const addKnowledge = (data: { title: string; category: string; content: string }) =>
  api<KnowledgeItem>("/api/v1/knowledge/add", { method: "POST", body: JSON.stringify(data) });

// Security
export const fetchPermissions = () =>
  api<{ permissions: PermissionView[] }>("/api/v1/security/permissions");

export const fetchApprovals = () =>
  api<{ approvals: unknown[] }>("/api/v1/control/approvals");

// Logs
export const fetchLogs = (level = "info", limit = 100) =>
  api<{ entries: { timestamp: string; level: string; message: string }[]; total: number }>(`/api/v1/logs?level=${level}&limit=${limit}`);

// Inspector
export const fetchInspectorRuntime = () => api("/api/v1/inspector/runtime");
export const fetchInspectorCheckpoints = (limit = 8, keepLatestPerTask = 20) =>
  api<CheckpointDiagnostics>(
    `/api/v1/inspector/checkpoints?limit=${limit}&keep_latest_per_task=${keepLatestPerTask}`,
  );
export const fetchRuns = (limit = 20) => api("/api/v1/runtime/runs?limit=" + limit);
export const fetchRunEvents = (runId: string, afterSequence = 0) =>
  api<{ run_id: string; events: Partial<RuntimeEventEnvelope>[]; next_after_sequence: number }>(
    `/api/v1/runtime/runs/${runId}/events?after_sequence=${afterSequence}&limit=200`,
  );

// Developer Platform

export interface DeveloperOverview {
  workspace: string;
  projects: { total: number; active: number };
  runs: { total: number; active: number };
  experiments: { total: number; benchmarked: number; production: number };
  models: { total: number; enabled: number; healthy: number; recoverable_operations: number };
}

export interface DeveloperProject {
  project_id: string;
  name: string;
  description: string;
  status: string;
  owner: string;
  created_at: string;
  updated_at: string;
  progress?: {
    total_work_items: number;
    completed: number;
    running: number;
    blocked: number;
    progress_pct: number;
    next_action: string;
    health: string;
  } | null;
}

export interface DeveloperRun {
  run_id: string;
  task_id: string;
  state: string;
  current_step: string;
  total_steps: number;
  completed_steps: number;
  progress_pct: number;
  created_at: string;
  updated_at: string;
  last_sequence: number;
}

export interface DeveloperExperiment {
  experiment_id: string;
  hypothesis: string;
  baseline_name: string;
  candidate_name: string;
  state: string;
  sample_size: number;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface ExperimentResultView {
  experiment_id: string;
  run_id: string;
  state: string;
  baseline_score: number;
  candidate_score: number;
  improvement: number;
  significant: boolean;
  p_value: number;
  effect_size: number;
  ci_lower: number;
  ci_upper: number;
  sample_size: number;
  completed_at: string;
}

export interface ModelLabSnapshot {
  models: Array<{
    model_id: string;
    display_name: string;
    provider_id: string;
    endpoint_type: string;
    state: string;
    health: string;
    capabilities: string[];
    capability_scores: Record<string, number>;
    evaluation?: Record<string, unknown> | null;
  }>;
  summary: { total: number; enabled: number; healthy: number; recoverable_operations: number };
  rankings: Array<{
    model_id: string;
    provider_id: string;
    sample_count: number;
    success_rate: number;
    avg_latency_ms: number;
    avg_cost_usd: number;
  }>;
  recent_observations: Array<Record<string, unknown>>;
  costs: Array<Record<string, unknown>>;
  evidence_status: string;
}

export const fetchDeveloperOverview = () => api<DeveloperOverview>("/api/v1/developer/overview");
export const fetchDeveloperProjects = () =>
  api<{ projects: DeveloperProject[]; total: number }>("/api/v1/developer/projects");
export const createDeveloperProject = (name: string, description: string) =>
  api<DeveloperProject>("/api/v1/developer/projects", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
export const developerProjectAction = (projectId: string, action: string) =>
  api<DeveloperProject>(`/api/v1/developer/projects/${encodeURIComponent(projectId)}/action`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
export const fetchDeveloperRuns = (limit = 100) =>
  api<{ runs: DeveloperRun[]; total: number }>(`/api/v1/developer/runs?limit=${limit}`);
export const fetchDeveloperExperiments = () =>
  api<{
    experiments: DeveloperExperiment[];
    results: ExperimentResultView[];
    summary: { total: number; benchmarked: number; production: number };
  }>("/api/v1/developer/experiments");
export const createDeveloperExperiment = (values: {
  hypothesis: string;
  baseline_name: string;
  candidate_name: string;
}) => api<DeveloperExperiment>("/api/v1/developer/experiments", {
  method: "POST",
  body: JSON.stringify(values),
});
export const evaluateDeveloperExperiment = (
  experimentId: string,
  baselineScores: number[],
  candidateScores: number[],
) => api<ExperimentResultView>(
  `/api/v1/developer/experiments/${encodeURIComponent(experimentId)}/evaluate`,
  {
    method: "POST",
    body: JSON.stringify({ baseline_scores: baselineScores, candidate_scores: candidateScores }),
  },
);
export const fetchModelLab = () => api<ModelLabSnapshot>("/api/v1/developer/model-lab");

export interface WorkbenchFileEntry {
  path: string;
  size_bytes: number;
  modified_at: string;
  language: string;
}

export interface WorkbenchProfile {
  name: "python" | "python-compile" | "pytest" | "node" | "cargo-test" | string;
  available: boolean;
  executable: string;
}

export interface WorkbenchListing {
  workspace: string;
  path: string;
  files: WorkbenchFileEntry[];
  total: number;
  truncated: boolean;
  profiles: WorkbenchProfile[];
}

export interface WorkbenchFile {
  path: string;
  content: string;
  size_bytes: number;
  sha256: string;
  language: string;
}

export interface WorkbenchPreview {
  path: string;
  exists: boolean;
  changed: boolean;
  before_sha256: string;
  after_sha256: string;
  size_bytes: number;
  diff: string;
}

export interface WorkbenchWriteResult extends WorkbenchPreview {
  ok: boolean;
  run_id: string;
  backup_path: string;
}

export interface WorkbenchRunResult {
  ok: boolean;
  run_id: string;
  profile: string;
  target: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  runtime_seconds: number;
  limit_exceeded: string;
  sandbox_id: string;
}

export interface CapabilityAvailability {
  available: Array<{ name: string; provider: string; category: string; risk: string; executor_type: string }>;
  unavailable: Array<{ name: string; provider: string; category: string; risk: string; executor_type: string; reason: string }>;
  summary: { registered: number; available: number; unavailable: number };
}

export const fetchWorkbenchFiles = (path = ".", limit = 500) => {
  const params = new URLSearchParams({ path, limit: String(limit) });
  return api<WorkbenchListing>(`/api/v1/developer/workspace/files?${params.toString()}`);
};

export const fetchWorkbenchFile = (path: string) =>
  api<WorkbenchFile>(`/api/v1/developer/workspace/file?path=${encodeURIComponent(path)}`);

export const searchWorkbench = (query: string, path = ".", limit = 200) => {
  const params = new URLSearchParams({ q: query, path, limit: String(limit) });
  return api<{ query: string; matches: Array<{ path: string; line: number; text: string }>; total: number; truncated: boolean }>(
    `/api/v1/developer/workspace/search?${params.toString()}`,
  );
};

export const previewWorkbenchWrite = (path: string, content: string, expectedSha256: string) =>
  api<WorkbenchPreview>("/api/v1/developer/workspace/preview", {
    method: "POST",
    body: JSON.stringify({ path, content, expected_sha256: expectedSha256 }),
  });

export const writeWorkbenchFile = (path: string, content: string, expectedSha256: string) =>
  api<WorkbenchWriteResult>("/api/v1/developer/workspace/write", {
    method: "POST",
    body: JSON.stringify({ path, content, expected_sha256: expectedSha256 }),
  });

export const runWorkbenchProfile = (profile: string, target: string, timeoutSeconds = 60) =>
  api<WorkbenchRunResult>("/api/v1/developer/workspace/run", {
    method: "POST",
    body: JSON.stringify({ profile, target, timeout_seconds: timeoutSeconds }),
  });

export const fetchCapabilityAvailability = () =>
  api<CapabilityAvailability>("/api/v1/developer/capabilities");
export interface GlobalSearchResult {
  kind: "conversation" | "file" | "artifact" | "run" | string;
  id: string;
  title: string;
  detail: string;
  path?: string;
}

export const globalSearch = (query: string, limit = 40) => {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return api<{ query: string; scope: string; results: GlobalSearchResult[]; count: number }>(
    `/api/v1/search?${params.toString()}`,
  );
};

// New: Nodes API

export interface NodeView {
  node_id: string;
  node_name: string;
  platform: string;
  arch: string;
  capabilities: string[];
  online: boolean;
  last_seen: string;
  status: string;
}

export const fetchNodes = (status = "") => {
  const params = status ? `?status=${status}` : "";
  return api<NodeView[]>(`/api/v1/nodes${params}`);
};

export const fetchNode = (nodeId: string) =>
  api<NodeView>(`/api/v1/nodes/${nodeId}`);

export const scanNodes = () =>
  api<{ nodes_found: number; nodes_online: number }>("/api/v1/nodes/scan", { method: "POST" });

// New: Approvals API

export const approvalAction = (requestId: string, action: "approve" | "deny") =>
  api(`/api/v1/approvals/${requestId}/${action}`, { method: "POST" });

// New: Runtime Events Stream

export interface RuntimeEventEnvelope {
  event_id: string;
  sequence: number;
  event_type: string;
  domain: string;
  source: string;
  timestamp: string;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  dedup_key: string;
}

export const fetchEventStream = (domain = "", sinceEventId = "", limit = 200) => {
  const params = new URLSearchParams();
  if (domain) params.set("domain", domain);
  if (sinceEventId) params.set("since_event_id", sinceEventId);
  params.set("limit", String(limit));
  return api<{ events: RuntimeEventEnvelope[]; count: number; domain: string; latest_event_id: string }>(
    `/api/v1/events/stream?${params}`,
  );
};

// New: Model Observations

export const fetchModelObservations = (modelId = "", providerId = "", capabilityId = "", limit = 100) => {
  const params = new URLSearchParams();
  if (modelId) params.set("model_id", modelId);
  if (providerId) params.set("provider_id", providerId);
  if (capabilityId) params.set("capability_id", capabilityId);
  params.set("limit", String(limit));
  return api<{ observations: unknown[]; count: number; statistics: unknown }>(
    `/api/v1/models/observations?${params}`,
  );
};

export const fetchModelRankings = (capabilityId = "", taskType = "") => {
  const params = new URLSearchParams();
  if (capabilityId) params.set("capability_id", capabilityId);
  if (taskType) params.set("task_type", taskType);
  return api<{ rankings: { model_id: string; provider_id: string; sample_count: number; success_rate: number; avg_latency_ms: number; avg_cost_usd: number }[]; count: number }>(
    `/api/v1/models/rankings?${params}`,
  );
};

// New: Execution Traces

export interface TraceSpanView {
  span_id: string;
  trace_id: string;
  parent_span_id: string;
  span_kind: string;
  span_name: string;
  status: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  model_id?: string;
  provider_id?: string;
  capability_id?: string;
  node_id?: string;
  result_summary?: string;
  error_message?: string;
}

export interface ExecutionTraceView {
  trace_id: string;
  session_id: string;
  task_id: string;
  root_span_id: string;
  spans: TraceSpanView[];
  total_duration_ms: number;
  span_count: number;
  has_errors: boolean;
}

export const fetchTrace = (traceId: string) =>
  api<ExecutionTraceView>(`/api/v1/traces/${traceId}`);

export const fetchTraceTimeline = (traceId: string) =>
  api<{ trace_id: string; spans: TraceSpanView[]; count: number; global_statistics: unknown }>(
    `/api/v1/traces/${traceId}/timeline`,
  );

// Governed Research Evidence

export interface ResearchNetworkStatus {
  gateway: "governed" | string;
  available: boolean;
  network_scope: string;
  methods: string[];
  max_response_bytes: number;
  max_request_body_bytes: number;
  credential_boundary: string;
  redirect_revalidation: boolean;
  dns_pinning: boolean;
  compressed_responses: string;
  source_count: number;
  snapshot_count: number;
  artifact_count: number;
  claim_count: number;
  claim_evidence_count: number;
  claim_contract: string;
  claim_event_authority: string;
  evidence_level: string;
}

export interface ResearchSource {
  source_id: string;
  url: string;
  title: string;
  publisher: string;
  retrieved_at: string;
  retrieval_time: string;
  content_hash: string;
  mime_type: string;
  source_type: string;
  trust_tier: string;
  snapshot_location: string;
  snapshot_artifact_id: string;
  injection_risk: string;
}

export interface ResearchCitation {
  source_id: string;
  title: string;
  url: string;
  publisher: string;
  author: string;
  publication_time: string;
  retrieved_at: string;
  content_hash: string;
  snapshot_artifact_id: string;
  formatted: string;
}

export interface ResearchSearchRequest {
  request_id: string;
  query: string;
  max_results: number;
  network_scope: "public_internet";
  max_response_bytes: number;
  timeout_seconds: number;
}

export interface ResearchSearchResultItem {
  rank: number;
  title: string;
  url: string;
  snippet: string;
}
export interface ResearchFetchRequest {
  request_id: string;
  method: "GET" | "HEAD" | "POST";
  url: string;
  body?: string;
  credential_ref?: string;
  network_scope: "public_internet";
  max_response_bytes: number;
  timeout_seconds: number;
}

export interface ResearchFetchResult {
  ok: boolean;
  url: string;
  final_url: string;
  status_code: number;
  content: string;
  content_hash: string;
  content_type: string;
  size_bytes: number;
  snapshot_id: string;
  snapshot_artifact_id: string;
  source_id: string;
  retrieved_at: string;
  redirect_chain: string[];
  run_id: string;
  request_id: string;
  citation?: ResearchCitation;
  injection_scan_result?: {
    safe: boolean;
    risk_level: string;
    detected_patterns: string[];
    blocked: boolean;
    reason: string;
  };
}

export const fetchResearchNetworkStatus = () =>
  api<ResearchNetworkStatus>("/api/v1/research/network/status");

export const fetchResearchSources = (limit = 100) =>
  api<{ sources: ResearchSource[]; total: number }>("/api/v1/research/sources?limit=" + limit);

export const fetchResearchSource = (sourceId: string) =>
  api<{ source: ResearchSource; snapshots: unknown[]; artifact: unknown | null; citation: ResearchCitation }>(
    "/api/v1/research/sources/" + encodeURIComponent(sourceId),
  );

export interface ResearchSearchResult {
  ok: boolean;
  query: string;
  results: ResearchSearchResultItem[];
  search_evidence: ResearchFetchResult;
  request_id: string;
  run_id: string;
}

export const searchResearchWeb = (request: ResearchSearchRequest) =>
  api<ResearchSearchResult>("/api/v1/research/search", {
    method: "POST",
    body: JSON.stringify(request),
  });
export const fetchResearchUrl = (request: ResearchFetchRequest) =>
  api<ResearchFetchResult>("/api/v1/research/fetch", {
    method: "POST",
    body: JSON.stringify(request),
  });

export type ClaimVerificationState =
  | "unverified"
  | "supported"
  | "partially_supported"
  | "conflicted"
  | "rejected";

export interface ResearchClaim {
  claim_id: string;
  statement: string;
  task_id: string;
  run_id: string;
  trace_id: string;
  evidence_refs: string[];
  source_refs: string[];
  snapshot_refs: string[];
  confidence: number;
  created_by: string;
  created_at: string;
  verification_state: ClaimVerificationState;
  provenance: Record<string, unknown>;
}

export interface ResearchClaimEvidence {
  evidence_id: string;
  claim_id: string;
  source_id: string;
  relation: string;
  strength: number;
  description: string;
  snapshot_ref: string;
  artifact_ref: string;
  created_at: string;
  provenance: Record<string, unknown>;
}

export interface ResearchClaimDetail {
  claim: ResearchClaim;
  evidence: ResearchClaimEvidence[];
  source_refs: string[];
  snapshot_refs: string[];
  artifact_refs: string[];
  sources: Array<ResearchSource & { citation: ResearchCitation }>;
  snapshots: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  trace_complete: boolean;
}

export interface ResearchClaimCreateRequest {
  statement: string;
  source_refs: string[];
  confidence: number;
  created_by?: string;
}

export const fetchResearchClaims = (limit = 100) =>
  api<{ claims: ResearchClaim[]; total: number; summary: Record<string, number> }>(
    "/api/v1/research/claims?limit=" + limit,
  );

export const fetchResearchClaim = (claimId: string) =>
  api<ResearchClaimDetail>("/api/v1/research/claims/" + encodeURIComponent(claimId));

export const createResearchClaim = (request: ResearchClaimCreateRequest) =>
  api<ResearchClaimDetail>("/api/v1/research/claims", {
    method: "POST",
    body: JSON.stringify(request),
  });

export const verifyResearchClaim = (
  claimId: string,
  verificationState?: ClaimVerificationState,
) =>
  api<ResearchClaimDetail>(
    "/api/v1/research/claims/" + encodeURIComponent(claimId) + "/verify",
    {
      method: "POST",
      body: JSON.stringify(verificationState ? { verification_state: verificationState } : {}),
    },
  );

// Live Event Subscription (polling-based SSE via API)

function normalizeRuntimeEvent(event: Partial<RuntimeEventEnvelope>): RuntimeEventEnvelope {
  return {
    event_id: event.event_id ?? crypto.randomUUID(),
    sequence: event.sequence ?? 0,
    event_type: event.event_type ?? "runtime.unknown",
    domain: event.domain ?? "runtime",
    source: event.source ?? "runtime",
    timestamp: event.timestamp ?? new Date().toISOString(),
    payload: event.payload ?? {},
    metadata: event.metadata ?? {},
    dedup_key: event.dedup_key ?? event.event_id ?? "",
  };
}

export function subscribeRuntimeEvents(
  onEvent: (event: RuntimeEventEnvelope) => void,
  options: { domain?: string; intervalMs?: number } = {},
) {
  let active = true;
  let lastEventId = "";
  const intervalMs = Math.max(500, options.intervalMs || 1500);

  const poll = async () => {
    if (!active) return;
    try {
      const result = await fetchEventStream(options.domain || "", lastEventId, 100);
      if (result.events) {
        for (const event of result.events) {
          onEvent(normalizeRuntimeEvent(event));
          if (event.event_id) lastEventId = event.event_id;
        }
      }
    } catch {
      // Retry on next poll
    } finally {
      if (active) window.setTimeout(poll, intervalMs);
    }
  };
  void poll();
  return { close: () => { active = false; }, lastEventId: () => lastEventId };
}

export function subscribeRunEvents(
  runId: string,
  onEvent: (event: unknown) => void,
  options: { intervalMs?: number; afterSequence?: number } = {},
) {
  let active = true;
  let afterSequence = Math.max(0, options.afterSequence || 0);
  const intervalMs = Math.max(250, options.intervalMs || 1000);

  const poll = async () => {
    if (!active) return;
    try {
      const page = await fetchRunEvents(runId, afterSequence);
      for (const event of page.events) onEvent(normalizeRuntimeEvent(event));
      afterSequence = page.next_after_sequence;
    } catch {
      // Retry on transient failures
    } finally {
      if (active) window.setTimeout(poll, intervalMs);
    }
  };
  void poll();
  return { close: () => { active = false; }, cursor: () => afterSequence };
}

// Document Workbench
export interface DocumentRuntimeStatus {
  schema_version: string;
  workspace: string;
  documents: number;
  dependencies: Record<string, boolean>;
  formats: { docx: boolean; pdf: boolean };
  limits: { blocks: number; content_characters: number; output_bytes: number };
  event_authority: string;
  artifact_authority: string;
}

export interface DocumentBlockInput {
  kind: "paragraph" | "heading" | "bullet_list" | "numbered_list" | "table" | "code" | "citation" | "page_break";
  text?: string;
  level?: 1 | 2 | 3;
  items?: string[];
  rows?: string[][];
  language?: string;
  source_id?: string;
  snapshot_id?: string;
  url?: string;
}

export interface DocumentCreateRequest {
  title: string;
  subtitle?: string;
  author?: string;
  language?: string;
  preset?: "standard_business_brief" | "compact_reference_guide" | "narrative_proposal";
  blocks: DocumentBlockInput[];
}

export interface DocumentSummary {
  document_id: string;
  title: string;
  subtitle: string;
  preset: string;
  created_at: string;
  block_count: number;
  sha256: string;
  status?: string;
  error?: string;
}

export interface DocumentCreateResult extends DocumentCreateRequest {
  schema_version: string;
  document_id: string;
  created_at: string;
  sha256: string;
  artifact_id: string;
  run_id: string;
}

export interface DocumentRenderResult {
  document_id: string;
  ir_sha256: string;
  run_id: string;
  verified: boolean;
  outputs: Array<{
    ok: boolean;
    format: "docx" | "pdf";
    location: string;
    size_bytes: number;
    sha256: string;
    artifact_id: string;
    checks: string[];
    page_count?: number;
  }>;
}

export const fetchDocumentStatus = () => api<DocumentRuntimeStatus>("/api/v1/documents/status");
export const fetchDocuments = () => api<{ documents: DocumentSummary[]; total: number }>("/api/v1/documents");
export const createDocument = (request: DocumentCreateRequest) =>
  api<DocumentCreateResult>("/api/v1/documents", { method: "POST", body: JSON.stringify(request) });
export const renderDocument = (documentId: string, formats: Array<"docx" | "pdf">) =>
  api<DocumentRenderResult>(`/api/v1/documents/${encodeURIComponent(documentId)}/render`, {
    method: "POST",
    body: JSON.stringify({ formats }),
  });

// Environment Inspector
export interface EnvironmentProviderStatus {
  provider_id: string;
  contract_version: string;
  available: boolean;
  environment_type: "local_sandbox" | "oci_container";
  evidence_level: string;
  engine?: string;
  hard_network_isolation?: boolean;
  filesystem_namespace_isolation?: boolean;
  limitations?: string[];
}

export interface EnvironmentRuntimeStatus {
  schema_version: string;
  workspace: string;
  environments: number;
  providers: EnvironmentProviderStatus[];
  compatibility: Record<string, {
    product_version: string;
    kernel_version: string;
    nki_version: number;
    runtime_api_version: string;
    environment_contract_version: string;
    provider_contract_version: string;
    compatible: boolean;
    issues: string[];
  }>;
  defaults: Record<string, string | boolean>;
  event_authority: string;
  artifact_authority: string;
  state_authority: string;
}

export interface WorkspaceMountInput {
  source: string;
  target: string;
  mode: "read-only" | "read-write" | "artifact-output-only";
}

export interface EnvironmentCreateRequest {
  environment_type: "local_sandbox" | "oci_container";
  provider: "local-sandbox" | "oci";
  image?: string;
  architecture?: string;
  os?: string;
  cpu_limit: number;
  memory_limit_mb: number;
  gpu_policy: "none" | "compute";
  network_policy: { mode: "none" | "http"; allowed_hosts?: string[] };
  filesystem_policy: { read_only_root: true; temporary_filesystem_mb: number };
  device_policy: { gpu: "none" | "compute"; devices: string[] };
  workspace_mounts: WorkspaceMountInput[];
  lifetime_seconds: number;
  task_id?: string;
  run_id?: string;
  trace_id?: string;
}

export interface EnvironmentRecord extends EnvironmentCreateRequest {
  schema_version: string;
  environment_id: string;
  state: "created" | "preparing" | "ready" | "running" | "suspended" | "stopping" | "stopped" | "destroyed" | "failed" | "invalid";
  provider_handle: string;
  created_at: string;
  updated_at: string;
  last_error: string;
  sha256: string;
  expired?: boolean;
  artifact_id?: string;
  operation_run_id?: string;
  error?: string;
}

export interface EnvironmentCommandRequest {
  argv: string[];
  cwd?: string;
  timeout_seconds?: number;
  max_output_bytes?: number;
  env?: Record<string, string>;
}

export interface EnvironmentRunResult {
  environment_id: string;
  state: string;
  operation_run_id: string;
  artifact_id: string;
  artifact: { location: string; sha256: string; size_bytes: number };
  ok: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
  wall_time_seconds: number;
  peak_memory_bytes: number;
  timed_out: boolean;
  output_truncated: boolean;
}

export const fetchEnvironmentStatus = () => api<EnvironmentRuntimeStatus>("/api/v1/environments/status");
export const fetchEnvironments = () => api<{ environments: EnvironmentRecord[]; total: number }>("/api/v1/environments");
export const createEnvironment = (request: EnvironmentCreateRequest) =>
  api<EnvironmentRecord>("/api/v1/environments", { method: "POST", body: JSON.stringify(request) });
export const startEnvironment = (environmentId: string) =>
  api<EnvironmentRecord>(`/api/v1/environments/${encodeURIComponent(environmentId)}/start`, { method: "POST" });
export const runEnvironment = (environmentId: string, request: EnvironmentCommandRequest) =>
  api<EnvironmentRunResult>(`/api/v1/environments/${encodeURIComponent(environmentId)}/run`, {
    method: "POST",
    body: JSON.stringify(request),
  });
export const stopEnvironment = (environmentId: string) =>
  api<EnvironmentRecord>(`/api/v1/environments/${encodeURIComponent(environmentId)}/stop`, { method: "POST" });
export const destroyEnvironment = (environmentId: string) =>
  api<EnvironmentRecord>(`/api/v1/environments/${encodeURIComponent(environmentId)}`, { method: "DELETE" });
export const fetchEnvironmentLogs = (environmentId: string) =>
  api<{ environment_id: string; provider: string; state: string; text: string }>(
    `/api/v1/environments/${encodeURIComponent(environmentId)}/logs`,
  );


// Simulation Workbench
export interface SimulationRuntimeStatus {
  schema_version: string;
  simulation_contract: string;
  simulation_run_contract: string;
  environment_contract: string;
  workspace: string;
  simulations: number;
  runs: number;
  completed: number;
  failed: number;
  active: number;
  built_in_models: Array<{
    model_ref: string;
    solver: string;
    deterministic: boolean;
    evidence_level: string;
  }>;
  scientific_providers: Record<string, string>;
  defaults: Record<string, string | number | boolean>;
  limitations: string[];
  event_authority: string;
  artifact_authority: string;
  execution_authority: string;
}

export interface SimulationResourceBudget {
  cpu_limit: number;
  memory_limit_mb: number;
  wall_time_seconds: number;
  max_cases: number;
  max_retries: number;
  max_output_bytes: number;
}

export interface SimulationCreateRequest {
  model_ref: string;
  environment_ref?: string;
  environment_type: "local_sandbox" | "oci_container";
  provider: "local-sandbox" | "oci";
  image?: string;
  initial_state: Record<string, number>;
  boundary_conditions: Record<string, number>;
  parameters: Record<string, number>;
  solver: "explicit-euler";
  time_step: number;
  duration: number;
  seed: number;
  resource_budget: SimulationResourceBudget;
  network_policy: { mode: "none" };
  metric_schema: string[];
  output_schema: Array<"json" | "csv" | "svg">;
  parameter_space: Record<string, number[]>;
  numerical_tolerance: { absolute: number; relative: number };
  task_id?: string;
  trace_id?: string;
}

export interface SimulationRecord extends SimulationCreateRequest {
  schema_version: string;
  simulation_id: string;
  created_at: string;
  state: "created" | "running" | "completed" | "failed" | "cancelled" | "invalid";
  last_error: string;
  sha256: string;
  artifact_id?: string;
  operation_run_id?: string;
  error?: string;
}

export interface SimulationArtifact {
  name: string;
  location: string;
  size_bytes: number;
  sha256: string;
  artifact_id: string;
}

export interface SimulationCase {
  case_id: number;
  parameters: Record<string, number>;
  metrics: Record<string, number>;
  last_temperature_rate: number;
}

export interface SimulationExecutionAttempt {
  attempt: number;
  ok: boolean;
  exit_code: number;
  timed_out: boolean;
  operation_run_id: string;
  artifact_id: string;
}

export interface SimulationRunRecord {
  schema_version: string;
  simulation_id: string;
  simulation_run_id: string;
  event_run_id: string;
  state: "completed" | "failed" | "cancelled" | "invalid";
  replay_of: string;
  started_at: string;
  completed_at: string;
  model_ref: string;
  solver: string;
  environment_id: string;
  execution_attempts: SimulationExecutionAttempt[];
  spec_sha256: string;
  case_count: number;
  cases: SimulationCase[];
  result_digest: string;
  artifacts: SimulationArtifact[];
  manifest_artifact_id: string;
  reproducibility: Record<string, unknown>;
  replay: {
    verified: boolean;
    matching_contract: boolean;
    within_tolerance: boolean;
    maximum_absolute_error: number;
    absolute_tolerance: number;
    relative_tolerance: number;
  } | null;
  sha256: string;
  error?: string;
}

export const fetchSimulationStatus = () =>
  api<SimulationRuntimeStatus>("/api/v1/simulations/status");

export const fetchSimulations = () =>
  api<{ simulations: SimulationRecord[]; total: number }>("/api/v1/simulations");

export const fetchSimulationRuns = (simulationId = "", limit = 100) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (simulationId) params.set("simulation_id", simulationId);
  return api<{ runs: SimulationRunRecord[]; total: number }>(
    `/api/v1/simulations/runs?${params.toString()}`,
  );
};

export const createSimulation = (request: SimulationCreateRequest) =>
  api<SimulationRecord>("/api/v1/simulations", {
    method: "POST",
    body: JSON.stringify(request),
  });

export const runSimulation = (simulationId: string, replayOf = "") =>
  api<SimulationRunRecord>(
    `/api/v1/simulations/${encodeURIComponent(simulationId)}/run`,
    {
      method: "POST",
      body: JSON.stringify(replayOf ? { replay_of: replayOf } : {}),
    },
  );

export const replaySimulation = (runId: string) =>
  api<SimulationRunRecord>(
    `/api/v1/simulations/runs/${encodeURIComponent(runId)}/replay`,
    { method: "POST", body: JSON.stringify({}) },
  );

export const cancelSimulation = (simulationId: string) =>
  api<{ simulation_id: string; simulation_run_id: string; cancellation_requested: boolean }>(
    `/api/v1/simulations/${encodeURIComponent(simulationId)}/cancel`,
    { method: "POST", body: JSON.stringify({}) },
  );


export interface ScientificProviderStatus {
  available: boolean;
  version: string;
  capabilities: string[];
  error: string;
}

export interface ScientificRuntimeStatus {
  schema_version: string;
  analysis_contract: string;
  result_contract: string;
  workspace: string;
  analyses: number;
  completed: number;
  failed: number;
  providers: Record<string, ScientificProviderStatus>;
  reference_tasks: Array<{
    analysis_type: string;
    simulation_model: string;
    outputs: string[];
    execution_authority: string;
  }>;
  event_authority: string;
  artifact_authority: string;
  claim_authority: string;
  document_authority: string;
  defaults: Record<string, unknown>;
  evidence_level: string;
}

export interface ScientificCaseResult {
  case_id: number;
  parameters: Record<string, number>;
  peak_temperature_kelvin: number;
  final_temperature_kelvin: number;
  radiative_equilibrium_kelvin: number;
  mission_safety_margin_kelvin: number;
  maximum_reference_error_kelvin: number;
  reference_rmse_kelvin: number;
  within_reference_tolerance: boolean;
  safe_during_simulated_duration: boolean;
}

export interface ScientificAnalysisRecord {
  schema_version: string;
  analysis_id: string;
  analysis_type: string;
  simulation_id: string;
  simulation_run_id: string;
  event_run_id: string;
  state: "completed" | "failed" | "invalid";
  reference_tolerance_kelvin: number;
  reference_verified: boolean;
  maximum_reference_error_kelvin: number;
  safe_during_simulated_duration: boolean;
  case_count: number;
  cases: ScientificCaseResult[];
  environment_id: string;
  environment_state: string;
  provider_inventory: Record<string, ScientificProviderStatus>;
  artifacts: SimulationArtifact[];
  claim_ids: string[];
  document: {
    document_id: string;
    verified: boolean;
    outputs: Array<{
      format: "docx" | "pdf";
      artifact_id: string;
      location: string;
      sha256: string;
      size_bytes: number;
    }>;
  } | null;
  error: string;
  sha256: string;
}

export const fetchScientificStatus = () =>
  api<ScientificRuntimeStatus>("/api/v1/scientific/status");

export const fetchScientificAnalyses = () =>
  api<{ analyses: ScientificAnalysisRecord[]; total: number }>(
    "/api/v1/scientific/analyses",
  );

export const analyzeSimulationRun = (
  simulationRunId: string,
  referenceToleranceKelvin = 0.05,
) =>
  api<ScientificAnalysisRecord>("/api/v1/scientific/analyses", {
    method: "POST",
    body: JSON.stringify({
      simulation_run_id: simulationRunId,
      analysis_type: "spacecraft-thermal-analysis/v1",
      reference_solver: "scipy.solve_ivp",
      reference_tolerance_kelvin: referenceToleranceKelvin,
      report_formats: ["docx", "pdf"],
    }),
  });
