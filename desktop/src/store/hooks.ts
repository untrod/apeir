/**
 * React hooks for consuming the EntityStore.
 *
 * Every hook returns real data from the store — no mocks, no local simulation.
 * Components subscribe to fine-grained slices for optimal re-rendering.
 */

import { useState, useEffect, useCallback, useRef, useSyncExternalStore } from "react";
import { entityStore } from "./entityStore";
import { fetchUsageSummary, getConfig, getRuntimeConfigVersion, subscribeRuntimeConfig } from "../lib/api";
import type {
  EntityId,
  Conversation, Session, Message,
  Task, Plan, Approval, Artifact, Verification,
  Node, Model, Evidence, UsageRecord, CostSummary,
  WorkspaceEntry,
  RuntimeEventEnvelope,
  SequenceNumber,
} from "./types";


// Core hook — subscribe to entire store


function useStore() {
  return useSyncExternalStore(
    (cb) => entityStore.subscribe(cb),
    () => entityStore.getState(),
  );
}


// Conversations


export function useConversations(): Conversation[] {
  const state = useStore();
  return Object.values(state.conversations).sort(
    (a, b) => new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime(),
  );
}

export function useConversation(id: EntityId): Conversation | null {
  const state = useStore();
  return state.conversations[id] || null;
}


// Sessions


export function useSessions(): Session[] {
  const state = useStore();
  return Object.values(state.sessions);
}

export function useActiveSession(): Session | null {
  const state = useStore();
  return Object.values(state.sessions).find((s) => s.status === "active") || null;
}


// Messages


export function useMessages(conversationId: EntityId): Message[] {
  const state = useStore();
  return Object.values(state.messages)
    .filter((m) => m.conversation_id === conversationId)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
}


// Tasks


export function useTasks(filter?: { status?: string; conversationId?: EntityId }): Task[] {
  const state = useStore();
  let tasks = Object.values(state.tasks);
  if (filter?.status) {
    tasks = tasks.filter((t) => t.status === filter.status);
  }
  if (filter?.conversationId) {
    tasks = tasks.filter((t) => t.conversation_id === filter.conversationId);
  }
  return tasks.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}

export function useTask(id: EntityId): Task | null {
  const state = useStore();
  return state.tasks[id] || null;
}

export function useActiveTasks(): Task[] {
  const state = useStore();
  return Object.values(state.tasks).filter((t) =>
    ["created", "queued", "planning", "awaiting_approval", "dispatching", "running", "waiting_for_model", "waiting_for_node", "waiting_user", "blocked", "paused", "recovering", "verifying"].includes(t.status),
  );
}


// Plans


export function usePlans(): Plan[] {
  const state = useStore();
  return Object.values(state.plans).sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
}

export function usePlan(id: EntityId): Plan | null {
  const state = useStore();
  return state.plans[id] || null;
}


// Approvals


export function useApprovals(filter?: { status?: string }): Approval[] {
  const state = useStore();
  let approvals = Object.values(state.approvals);
  if (filter?.status) {
    approvals = approvals.filter((a) => a.status === filter.status);
  }
  return approvals.sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
}

export function usePendingApprovals(): Approval[] {
  return useApprovals({ status: "requested" });
}

export function useApproval(id: EntityId): Approval | null {
  const state = useStore();
  return state.approvals[id] || null;
}


// Artifacts


export function useArtifacts(taskId?: EntityId): Artifact[] {
  const state = useStore();
  let arts = Object.values(state.artifacts);
  if (taskId) arts = arts.filter((a) => a.task_id === taskId);
  return arts.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}

export function useArtifact(id: EntityId): Artifact | null {
  const state = useStore();
  return state.artifacts[id] || null;
}


// Verifications


export function useVerifications(): Verification[] {
  const state = useStore();
  return Object.values(state.verifications);
}

export function useVerification(id: EntityId): Verification | null {
  const state = useStore();
  return state.verifications[id] || null;
}


// Nodes


export function useNodes(): Node[] {
  const state = useStore();
  return Object.values(state.nodes).sort((a, b) => a.name.localeCompare(b.name));
}

export function useNode(id: EntityId): Node | null {
  const state = useStore();
  return state.nodes[id] || null;
}

export function useOnlineNodes(): Node[] {
  const state = useStore();
  return Object.values(state.nodes).filter((n) => n.online);
}

export function usePrimaryNode(): Node | null {
  const state = useStore();
  return Object.values(state.nodes).find((n) => n.role === "primary") || null;
}


// Models


export function useModels(): Model[] {
  const state = useStore();
  return Object.values(state.models).sort((a, b) => a.display_name.localeCompare(b.display_name));
}

export function useModel(id: EntityId): Model | null {
  const state = useStore();
  return state.models[id] || null;
}


// Evidence


export function useEvidence(taskId?: EntityId): Evidence[] {
  const state = useStore();
  let ev = Object.values(state.evidence);
  if (taskId) ev = ev.filter((e) => e.task_id === taskId);
  return ev;
}


// Usage / Cost


export function useUsage(): UsageRecord[] {
  const state = useStore();
  return Object.values(state.usage);
}

type UsageReader = { version: number; active: () => boolean };
const usageReaders = new Set<UsageReader>();
let usageTimer: number | undefined;
let usageFlight: { version: number; key: object; promise: Promise<void>; abort: AbortController } | null = null;
const visibleDocument = () => document.visibilityState !== "hidden";
const hasVisibleUsageReader = () => [...usageReaders].some(reader => {
  try { return reader.version === getRuntimeConfigVersion() && reader.active() && visibleDocument(); } catch { return false; }
});

/** Shared transport only. The existing EntityStore/CostController still own data. */
export function refreshCostSummary(replacePending = false): Promise<void> {
  const version = getRuntimeConfigVersion();
  if (!hasVisibleUsageReader()) return Promise.resolve();
  if (usageFlight?.version === version && !replacePending) return usageFlight.promise;
  usageFlight?.abort.abort();
  const controller = getConfig().url;
  const sequence = entityStore.beginUsageRead(controller, version);
  const key = {};
  const abort = new AbortController();
  const promise = (async () => {
    try {
      const summary = await fetchUsageSummary(undefined, { signal: abort.signal });
      if (usageFlight?.key === key && hasVisibleUsageReader() && getRuntimeConfigVersion() === version && getConfig().url === controller) entityStore.finishUsageRead(sequence, summary);
    } catch {
      if (usageFlight?.key === key && hasVisibleUsageReader() && getRuntimeConfigVersion() === version) entityStore.failUsageRead(sequence);
    }
  })().finally(() => { if (usageFlight?.key === key) usageFlight = null; });
  usageFlight = { version, key, promise, abort };
  return promise;
}

function subscribeUsage(reader: UsageReader) {
  const alreadyVisible = hasVisibleUsageReader();
  usageReaders.add(reader);
  let frame: number | undefined;
  if (!alreadyVisible && hasVisibleUsageReader()) void refreshCostSummary();
  else if (!alreadyVisible) frame = requestAnimationFrame(() => { if (usageReaders.has(reader)) void refreshCostSummary(); });
  const visible = () => { if (visibleDocument()) void refreshCostSummary(); };
  if (usageTimer === undefined) {
    // Retire a stalled read at the existing five-second refresh boundary.
    // This aborts only an HTTP read, never a model operation or its accounting.
    usageTimer = window.setInterval(() => { void refreshCostSummary(true); }, 5000);
    document.addEventListener("visibilitychange", visible);
    visibilityListener = visible;
  }
  return () => {
    usageReaders.delete(reader);
    if (frame !== undefined) cancelAnimationFrame(frame);
    if (!usageReaders.size && usageTimer !== undefined) {
      window.clearInterval(usageTimer); usageTimer = undefined;
      usageFlight?.abort.abort(); usageFlight = null;
      if (visibilityListener) document.removeEventListener("visibilitychange", visibilityListener);
      visibilityListener = undefined;
    }
  };
}
let visibilityListener: (() => void) | undefined;

export function useCostSummary(isActive = visibleDocument): CostSummary {
  const version = useRuntimeConfigVersion();
  const activity = useRef(isActive); activity.current = isActive;
  const state = useSyncExternalStore(
    (listener) => entityStore.subscribe(listener),
    () => entityStore.getState().usage_accounting,
  );
  useEffect(() => subscribeUsage({ version, active: () => activity.current() }), [version]);
  if (state.configuration_version !== version || state.controller !== getConfig().url) {
    return { status: "loading", controller: getConfig().url, configuration_version: version, summary: null, error: null };
  }
  return state;
}

export function useRuntimeConfigVersion(): number {
  return useSyncExternalStore(subscribeRuntimeConfig, getRuntimeConfigVersion);
}


// Workspace


export function useWorkspace(): WorkspaceEntry[] {
  const state = useStore();
  return Object.values(state.workspace);
}


// Store status


export function useStoreHydrated(): boolean {
  const state = useStore();
  return state.hydrated;
}

export function useEventCursor(domain: string): SequenceNumber {
  const state = useStore();
  return state.cursors[domain] || 0;
}
