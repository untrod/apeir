/**
 * EntityStore — Single source of truth for all Nous domain entities.
 *
 * Architecture:
 *   REST API → EntityStore ← RuntimeEvent stream
 *                  ↓
 *           IndexedDB (offline cache)
 *                  ↓
 *            React hooks (useConversation, useTasks, …)
 *
 * Key properties:
 *   - Event-driven: entities update via RuntimeEvent payloads
 *   - Deduplicated: event_id + dedup_key prevent double-processing
 *   - Sequenced: per-domain cursors enable reconnect backfill
 *   - Offline-first: IndexedDB persists state; rehydrates on load
 *   - Reconciled: server timestamps win conflicts via updated_at
 */

import type {
  EntityId, SequenceNumber, SchemaVersion,
  EntityStoreState,
  Conversation, Session, Message,
  Task, Plan, Approval, Artifact, Verification,
  Node, Model, Evidence, UsageRecord,
  WorkspaceEntry,
  RuntimeEventEnvelope,
} from "./types";


// IndexedDB helpers


const DB_NAME = "nous_entity_store";
const DB_VERSION = 1;
const STORE_NAME = "state";

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE_NAME);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function loadCache(): Promise<EntityStoreState | null> {
  try {
    const db = await openDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).get("entity_state");
      tx.oncomplete = () => db.close();
      req.onsuccess = () => resolve(req.result ?? null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function saveCache(state: EntityStoreState): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(state, "entity_state");
    tx.oncomplete = () => db.close();
  } catch {
    // Offline — silent fail, data lives in memory
  }
}


// Initial state factory


const EMPTY_STATE: EntityStoreState = {
  schema_version: "1.0.0",
  conversations: {},
  sessions: {},
  messages: {},
  tasks: {},
  plans: {},
  approvals: {},
  artifacts: {},
  verifications: {},
  nodes: {},
  models: {},
  evidence: {},
  usage: {},
  workspace: {},
  cursors: {},
  hydrated: false,
};


// Dedup & conflict resolution


function isNewer(a: string | undefined, b: string): boolean {
  if (!a) return true;
  return new Date(b) > new Date(a);
}


// Store Implementation


type Listener = () => void;

class EntityStoreImpl {
  private state: EntityStoreState = { ...EMPTY_STATE };
  private listeners = new Set<Listener>();
  private saveTimer: ReturnType<typeof setTimeout> | null = null;

  /** Debounced persistence to IndexedDB */
  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      saveCache(this.state);
    }, 500);
  }

  /** Notify all React hooks */
  private notify(): void {
    this.scheduleSave();
    for (const fn of this.listeners) fn();
  }

  // Lifecycle

  async hydrate(): Promise<void> {
    const cached = await loadCache();
    if (cached) this.state = { ...EMPTY_STATE, ...cached };
    this.state.hydrated = true;
    this.notify();
  }

  getState(): EntityStoreState {
    return this.state;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  // Server reconciliation

  /** Replace all state with server snapshot (call on reconnect) */
  reconcile(serverState: Partial<EntityStoreState>): void {
    for (const [key, records] of Object.entries(serverState)) {
      if (key === "schema_version" || key === "cursors" || key === "hydrated") continue;
      if (typeof records === "object" && records !== null) {
        const existing = (this.state as any)[key] || {};
        for (const [id, record] of Object.entries(records as Record<string, any>)) {
          const current = existing[id];
          if (!current || isNewer(current.updated_at, record.updated_at)) {
            existing[id] = record;
          }
        }
      }
    }
    if (serverState.cursors) {
      for (const [domain, seq] of Object.entries(serverState.cursors)) {
        this.state.cursors[domain] = Math.max(this.state.cursors[domain] || 0, seq);
      }
    }
    this.state.hydrated = true;
    this.notify();
  }

  // Event ingestion

  /** Ingest a RuntimeEvent — dedup, update cursor, mutate entity */
  ingestEvent(event: RuntimeEventEnvelope): boolean {
    const domain = event.domain || event.event_type.split(".")[0];
    const lastSeq = this.state.cursors[domain] || 0;

    // Dedup: skip if we've already seen this sequence
    if (event.sequence > 0 && event.sequence <= lastSeq) return false;

    // Update cursor
    if (event.sequence > 0) {
      this.state.cursors[domain] = Math.max(lastSeq, event.sequence);
    }

    // Mutate state based on event type
    this.applyEvent(event);

    this.notify();
    return true;
  }

  private applyEvent(event: RuntimeEventEnvelope): void {
    const { event_type, payload } = event;

    // Task events
    if (event_type.startsWith("task.")) {
      const taskId = payload.task_id as string;
      if (!taskId) return;
      const existing = this.state.tasks[taskId] || this.emptyTask(taskId);
      const status = event_type.replace("task.", "") as Task["status"];
      this.state.tasks[taskId] = {
        ...existing,
        ...this.mapTaskPayload(payload),
        status,
        updated_at: event.timestamp,
      };
      // Task step events
      if (event_type.startsWith("task.step.")) {
        const stepId = payload.step_id as string;
        if (stepId && existing.steps) {
          const stepIdx = existing.steps.findIndex((s) => s.step_id === stepId);
          if (stepIdx >= 0) {
            existing.steps[stepIdx] = {
              ...existing.steps[stepIdx],
              status: event_type.replace("task.step.", "") as any,
              ...(event_type === "task.step.completed" ? { completed_at: event.timestamp } : {}),
              ...(event_type === "task.step.failed" ? { error: payload.error as string } : {}),
            };
          }
        }
      }
    }

    // Approval events
    if (event_type.startsWith("approval.")) {
      const reqId = (payload.request_id || payload.id) as string;
      if (!reqId) return;
      const status = event_type.replace("approval.", "") as Approval["status"];
      this.state.approvals[reqId] = {
        ...(this.state.approvals[reqId] || {} as Approval),
        id: reqId,
        request_id: reqId,
        capability_id: (payload.capability_id as string) || "",
        status,
        requester: (payload.requester as string) || (payload.source as string) || "",
        risk_level: (payload.risk_level as Approval["risk_level"]) || "medium",
        reason: (payload.reason as string) || "",
        resolved_at: status === "granted" || status === "denied" ? event.timestamp : undefined,
        schema_version: "1.0.0",
        updated_at: event.timestamp,
        created_at: this.state.approvals[reqId]?.created_at || event.timestamp,
      };
    }

    // Node events
    if (event_type.startsWith("node.")) {
      const nodeId = payload.node_id as string;
      if (!nodeId) return;
      const existing = this.state.nodes[nodeId] || {} as Node;
      const online = event_type === "node.online" ? true : event_type === "node.offline" ? false : existing.online;
      this.state.nodes[nodeId] = {
        ...existing,
        id: nodeId,
        online,
        last_seen: event.timestamp,
        updated_at: event.timestamp,
        schema_version: "1.0.0",
        created_at: existing.created_at || event.timestamp,
      };
    }

    // Plan events
    if (event_type.startsWith("plan.")) {
      const planId = payload.plan_id as string;
      if (!planId) return;
      const status = event_type.replace("plan.", "") as Plan["status"];
      this.state.plans[planId] = {
        ...(this.state.plans[planId] || {} as Plan),
        id: planId,
        title: (payload.title as string) || this.state.plans[planId]?.title || "",
        status,
        stages: (payload.stages as Plan["stages"]) || this.state.plans[planId]?.stages || [],
        schema_version: "1.0.0",
        updated_at: event.timestamp,
        created_at: this.state.plans[planId]?.created_at || event.timestamp,
      };
    }

    // Artifact events
    if (event_type.startsWith("artifact.")) {
      const artId = payload.artifact_id as string;
      if (!artId) return;
      this.state.artifacts[artId] = {
        ...(this.state.artifacts[artId] || {} as Artifact),
        id: artId,
        name: (payload.name as string) || this.state.artifacts[artId]?.name || artId,
        kind: (payload.kind as Artifact["kind"]) || "text",
        url: (payload.url as string) || "",
        size_bytes: (payload.size_bytes as number) || 0,
        content_hash: (payload.content_hash as string) || "",
        version: ((payload.version as number) || 0) + 1,
        verified: (payload.verified as boolean) || false,
        schema_version: "1.0.0",
        updated_at: event.timestamp,
        created_at: this.state.artifacts[artId]?.created_at || event.timestamp,
      };
    }

    // Verification events
    if (event_type.startsWith("verification.")) {
      const capId = payload.capability_id as string;
      if (!capId) return;
      const status = event_type.replace("verification.", "") as Verification["status"];
      this.state.verifications[capId] = {
        ...(this.state.verifications[capId] || {} as Verification),
        id: capId,
        capability_id: capId,
        status,
        evidence: (payload.evidence as Verification["evidence"]) || this.state.verifications[capId]?.evidence || {} as Verification["evidence"],
        stages: (payload.stages as Verification["stages"]) || [],
        schema_version: "1.0.0",
        updated_at: event.timestamp,
        created_at: this.state.verifications[capId]?.created_at || event.timestamp,
      };
    }

    if (event_type.startsWith("evidence.")) {
      const evId = payload.evidence_id as string || event.event_id;
      this.state.evidence[evId] = {
        id: evId,
        task_id: payload.task_id as string || "",
        kind: (payload.kind as Evidence["kind"]) || "execution",
        content_hash: (payload.content_hash as string) || "",
        signature: (payload.signature as string) || "",
        attested_by: (payload.attested_by as string) || event.source,
        chain_index: (payload.chain_index as number) || 0,
        schema_version: "1.0.0",
        updated_at: event.timestamp,
        created_at: event.timestamp,
      };
    }
  }

  private emptyTask(id: string): Task {
    return {
      id, name: id, status: "created", priority: "normal",
      steps: [], progress_pct: 0, cancellation_requested: false,
      recoverable: true,
      schema_version: "1.0.0",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  private mapTaskPayload(payload: Record<string, unknown>): Partial<Task> {
    return {
      name: (payload.name as string) || undefined,
      model_id: (payload.model_id as string) || undefined,
      node_id: (payload.node_id as string) || undefined,
      capability_id: (payload.capability_id as string) || undefined,
      plan_id: (payload.plan_id as string) || undefined,
      trace_id: (payload.trace_id as string) || undefined,
      progress_pct: (payload.progress_pct as number) ?? (payload.progress as number) ?? undefined,
      error: (payload.error as string) || undefined,
      result_summary: (payload.result_summary as string) || undefined,
      recoverable: (payload.recoverable as boolean) ?? true,
    };
  }

  // REST API data loading

  upsertTasks(tasks: Task[]): void {
    for (const t of tasks) {
      const existing = this.state.tasks[t.id];
      if (!existing || isNewer(existing.updated_at, t.updated_at)) {
        this.state.tasks[t.id] = t;
      }
    }
    this.notify();
  }

  upsertNodes(nodes: Node[]): void {
    for (const n of nodes) {
      const existing = this.state.nodes[n.id];
      if (!existing || isNewer(existing.updated_at, n.updated_at)) {
        this.state.nodes[n.id] = n;
      }
    }
    this.notify();
  }

  upsertModels(models: Model[]): void {
    // Remove records written by the pre-RC3 API shape, which did not expose
    // the canonical entity id expected by the desktop store.
    delete this.state.models.undefined;
    for (const m of models) {
      if (!m.id) continue;
      // The REST snapshot is authoritative and also repairs incomplete cache
      // entries written by older desktop schemas.
      this.state.models[m.id] = m;
    }
    this.notify();
  }

  upsertConversations(convos: Conversation[]): void {
    for (const c of convos) {
      const existing = this.state.conversations[c.id];
      if (!existing || isNewer(existing.updated_at, c.updated_at)) {
        this.state.conversations[c.id] = c;
      }
    }
    this.notify();
  }

  addMessage(msg: Message): void {
    this.state.messages[msg.id] = msg;
    if (msg.conversation_id && this.state.conversations[msg.conversation_id]) {
      this.state.conversations[msg.conversation_id].message_count++;
      this.state.conversations[msg.conversation_id].last_message_at = msg.created_at;
    }
    this.notify();
  }

  upsertMessages(messages: Message[]): void {
    for (const message of messages) {
      if (!message.id) continue;
      this.state.messages[message.id] = message;
    }
    this.notify();
  }

  upsertApprovals(approvals: Approval[]): void {
    for (const a of approvals) {
      this.state.approvals[a.id] = { ...a };
    }
    this.notify();
  }

  upsertArtifacts(artifacts: Artifact[]): void {
    for (const a of artifacts) {
      const existing = this.state.artifacts[a.id];
      if (!existing || isNewer(existing.updated_at, a.updated_at)) {
        this.state.artifacts[a.id] = a;
      }
    }
    this.notify();
  }

  upsertUsage(records: UsageRecord[]): void {
    for (const r of records) {
      this.state.usage[r.id] = r;
    }
    this.notify();
  }

  upsertWorkspace(entries: WorkspaceEntry[]): void {
    for (const w of entries) {
      this.state.workspace[w.id] = w;
    }
    this.notify();
  }

  // Actions
  // RC9: updateTaskStatus and requestCancellation are DEPRECATED.
  // State changes must only arrive via runtime events, never via optimistic local mutation.
  // See .audit/rc9/STATE_OWNERSHIP.md and EXECUTION_PATH.md

  /** @deprecated RC9 — Status changes must arrive via runtime events, not local writes. */
  updateTaskStatus(taskId: string, status: Task["status"]): void {
    if (this.state.tasks[taskId]) {
      this.state.tasks[taskId].status = status;
      this.state.tasks[taskId].updated_at = new Date().toISOString();
      this.notify();
    }
  }

  /** @deprecated RC9 — Cancellation must be confirmed via runtime event, not set locally. */
  requestCancellation(taskId: string): void {
    if (this.state.tasks[taskId]) {
      this.state.tasks[taskId].cancellation_requested = true;
      this.notify();
    }
  }

  clearStore(): void {
    this.state = { ...EMPTY_STATE };
    this.notify();
  }
}


// Singleton export


export const entityStore = new EntityStoreImpl();
