/**
 * Nous Entity Types — Canonical TypeScript definitions for all domain entities.
 *
 * SCHEMA VERSION: 1.0.0
 * This file is the authoritative type contract between Nous Runtime API and all frontend surfaces.
 * Every entity has a schema_version, an id field, and an updated_at timestamp for reconciliation.
 */


// Core Primitives


export type EntityId = string;
export type Timestamp = string; // ISO 8601
export type SchemaVersion = string; // semver
export type SequenceNumber = number;

/** Every entity stored in the EntityStore implements this */
export interface EntityBase {
  id: EntityId;
  schema_version: SchemaVersion;
  created_at: Timestamp;
  updated_at: Timestamp;
}


// Conversation & Session


export interface Conversation extends EntityBase {
  id: EntityId;
  title: string;
  session_id: EntityId;
  model_id?: string;
  message_count: number;
  last_message_at: Timestamp;
  pinned: boolean;
  archived: boolean;
}

export interface Session extends EntityBase {
  id: EntityId;
  status: "active" | "paused" | "closed" | "expired";
  context_snapshot_id?: string;
  token_count: number;
  message_count: number;
}

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface Message extends EntityBase {
  id: EntityId;
  conversation_id: EntityId;
  session_id: EntityId;
  role: MessageRole;
  content: string;
  model_id?: string;
  trace_id?: string;
  tokens_used?: number;
  cards: RuntimeEventEnvelope[];
}


// Task


export type TaskStatus =
  | "created" | "queued" | "planning" | "awaiting_approval"
  | "dispatching" | "running" | "waiting_for_model" | "waiting_for_node"
  | "waiting_user" | "paused" | "blocked" | "recovering" | "verifying"
  | "completed" | "completed_with_warnings"
  | "failed" | "failed_verification" | "cancelled";

export type TaskPriority = "low" | "normal" | "high" | "critical";

export interface TaskStep {
  step_id: EntityId;
  name: string;
  status: "pending" | "ready" | "running" | "completed" | "failed" | "skipped" | "blocked";
  started_at?: Timestamp;
  completed_at?: Timestamp;
  error?: string;
  retry_count: number;
  max_retries: number;
}

export interface Task extends EntityBase {
  id: EntityId;
  conversation_id?: EntityId;
  session_id?: EntityId;
  name: string;
  status: TaskStatus;
  priority: TaskPriority;
  model_id?: string;
  node_id?: string;
  capability_id?: string;
  plan_id?: string;
  trace_id?: string;
  steps: TaskStep[];
  progress_pct: number;
  duration_ms?: number;
  error?: string;
  result_summary?: string;
  cancellation_requested: boolean;
  recoverable: boolean;
  task_kind?: "work" | string;
  run_id?: EntityId;
  current_step?: EntityId;
  plan_revision?: number;
  artifact_refs?: string[];
}


// Plan


export interface PlanStage {
  name: string;
  description?: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  depends_on: EntityId[];
  task_ids: EntityId[];
}

export interface Plan extends EntityBase {
  id: EntityId;
  conversation_id?: EntityId;
  title: string;
  status: "created" | "running" | "completed" | "failed" | "cancelled";
  stages: PlanStage[];
  estimated_duration_ms?: number;
}


// Approval


export type ApprovalAction = "approve" | "deny";

export interface Approval extends EntityBase {
  id: EntityId;
  request_id: EntityId;
  capability_id: string;
  task_id?: EntityId;
  status: "requested" | "granted" | "denied" | "expired" | "superseded" | "escalated";
  requester: string;
  risk_level: "low" | "medium" | "high" | "critical";
  reason: string;
  resolved_at?: Timestamp;
  resolved_by?: string;
}


// Artifact


export type ArtifactKind = "code" | "image" | "json" | "markdown" | "text" | "binary" | "diff";

export interface Artifact extends EntityBase {
  id: EntityId;
  task_id?: EntityId;
  conversation_id?: EntityId;
  name: string;
  kind: ArtifactKind;
  mime_type: string;
  size_bytes: number;
  content_hash: string;
  url: string;
  preview_url?: string;
  version: number;
  verified: boolean;
}


// Verification


export interface VerificationEvidence {
  input_hash: string;
  output_hash: string;
  sandbox_attestation: string;
  capability_version: string;
  model_fingerprint: string;
  reproducibility_proof: string;
}

export interface Verification extends EntityBase {
  id: EntityId;
  task_id?: EntityId;
  capability_id: string;
  status: "started" | "passed" | "failed" | "repaired";
  stages: { name: string; status: string; detail?: string }[];
  evidence: VerificationEvidence;
  repaired_by?: string;
}


// Node


export type NodeRole = "primary" | "worker" | "standby";

export interface NodeCapability {
  name: string;
  version: string;
  status: "available" | "busy" | "offline";
}

export interface Node extends EntityBase {
  id: EntityId;
  name: string;
  role: NodeRole;
  platform: string;
  arch: string;
  online: boolean;
  last_seen: Timestamp;
  capabilities: NodeCapability[];
  active_task_count: number;
  total_task_count: number;
  network_latency_ms?: number;
  version: string;
  paired_at: Timestamp;
}


// Model


export type ModelProviderKind = "openai" | "anthropic" | "local" | "custom";

export interface ModelProbe {
  capability_id: string;
  success_rate: number;
  avg_latency_ms: number;
  avg_cost_usd: number;
  sample_count: number;
  last_probed_at: Timestamp;
}

export interface ModelCalibration {
  overall_score: number;
  error_rate: number;
  bias_indicators: Record<string, number>;
  last_calibrated_at: Timestamp;
}

export interface Model extends EntityBase {
  id: EntityId;
  display_name: string;
  provider_id: string;
  provider_kind: ModelProviderKind;
  state: "enabled" | "disabled" | "degraded" | "recovering";
  health: "healthy" | "degraded" | "unhealthy" | "unknown";
  capabilities: string[];
  probes: ModelProbe[];
  calibration?: ModelCalibration;
  cost_per_1k_tokens_usd: number;
  avg_latency_ms: number;
  token_limit: number;
  recoverable: boolean;
}


// Evidence


export interface Evidence extends EntityBase {
  id: EntityId;
  task_id: EntityId;
  verification_id?: EntityId;
  kind: "input" | "output" | "sandbox" | "execution" | "recovery";
  content_hash: string;
  signature: string;
  attested_by: string;
  chain_index: number;
}


// Usage / Cost


export interface UsageRecord extends EntityBase {
  id: EntityId;
  model_id: string;
  task_id?: EntityId;
  conversation_id?: EntityId;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  period_start: Timestamp;
  period_end: Timestamp;
}

export interface CostSummary {
  total_cost_usd: number;
  by_model: Record<string, number>;
  by_task: Record<string, number>;
  period_start: Timestamp;
  period_end: Timestamp;
}


// Runtime Event (canonical envelope)


export interface RuntimeEventEnvelope {
  event_id: EntityId;
  sequence: SequenceNumber;
  event_type: string;
  domain: string;
  source: string;
  timestamp: Timestamp;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  dedup_key: string;
}


// Workspace


export interface WorkspaceFile {
  path: string;
  name: string;
  kind: "file" | "directory";
  mime_type?: string;
  size_bytes?: number;
  modified_at: Timestamp;
  artifact_id?: EntityId;
  verified: boolean;
}

export interface WorkspaceEntry extends EntityBase {
  id: EntityId;
  root_path: string;
  files: WorkspaceFile[];
  pack_count: number;
  knowledge_count: number;
}


// Store State


export interface EntityStoreState {
  schema_version: SchemaVersion;
  conversations: Record<EntityId, Conversation>;
  sessions: Record<EntityId, Session>;
  messages: Record<EntityId, Message>;
  tasks: Record<EntityId, Task>;
  plans: Record<EntityId, Plan>;
  approvals: Record<EntityId, Approval>;
  artifacts: Record<EntityId, Artifact>;
  verifications: Record<EntityId, Verification>;
  nodes: Record<EntityId, Node>;
  models: Record<EntityId, Model>;
  evidence: Record<EntityId, Evidence>;
  usage: Record<EntityId, UsageRecord>;
  workspace: Record<EntityId, WorkspaceEntry>;
  /** Last seen event sequence for each domain (used for reconnect backfill) */
  cursors: Record<string, SequenceNumber>;
  /** Whether the store is hydrated from server */
  hydrated: boolean;
}
