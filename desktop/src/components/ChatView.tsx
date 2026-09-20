/**
 * ChatView — Chat-first interface consuming EntityStore and Composer.
 *
 * All state flows through the EntityStore:
 *   - Messages from store (via conversation)
 *   - Tasks, approvals, artifacts from store
 *   - Models, nodes from store
 *
 * No mocks. No local simulation. All real API + Runtime Events.
 */

import React, { useState, useRef, useEffect, useCallback } from "react";
import { colors, typo, radius, space, fadeIn } from "../design";
import { entityStore } from "../store";
import { useMessages, useActiveTasks, useModels, useNodes, useStoreHydrated } from "../store";
import type { RuntimeEventEnvelope, Conversation, Message as MessageType } from "../store";
import {
  approvalAction,
  describeRuntimeFailure,
  fetchConversation,
  fetchRunEvents,
  runPrompt,
  subscribeRunEvents,
} from "../lib/api";
import {
  RuntimeCard, TaskCard, ApprovalCard, VerificationCard, ArtifactCard, PlanCard,
  type PlanStage,
} from "./RuntimeCard";
import { Markdown } from "./Markdown";
import { Composer, type ComposerAttachment, type ComposerConstraints } from "./Composer";
import { toast } from "./Toast";
import { summarizeRuntimeActivity } from "../lib/runtimeActivity";


// Message Bubble


function MessageBubble({
  msg, onCardClick, onTraceClick,
}: {
  msg: { id: string; role: string; content: string; timestamp: string; traceId?: string; modelId?: string; cards?: RuntimeEventEnvelope[] };
  onCardClick: (event: RuntimeEventEnvelope) => void;
  onTraceClick: (traceId: string) => void;
}) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div style={{ textAlign: "center", padding: `${space.sm} 0`, fontSize: typo.xs, color: colors.textTertiary }}>
        {msg.content}
      </div>
    );
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column",
      alignItems: isUser ? "flex-end" : "flex-start",
      marginBottom: space.lg, ...fadeIn,
    }}>
      <div style={{ fontSize: typo.xs, fontWeight: typo.medium, color: colors.textTertiary, marginBottom: 4, paddingLeft: isUser ? 0 : space.sm, paddingRight: isUser ? space.sm : 0 }}>
        {isUser ? "You" : "APEIR"}
        {msg.modelId && !isUser && <span style={{ fontWeight: typo.normal }}>{" · "}{msg.modelId}</span>}
      </div>
      <div style={{
        maxWidth: "82%", padding: `${space.md} ${space.lg}`,
        borderRadius: radius.lg, fontSize: typo.base, lineHeight: typo.relaxed,
        background: isUser ? colors.accentSoft : colors.surface,
        border: `1px solid ${isUser ? "transparent" : colors.border}`,
        color: colors.text, wordBreak: "break-word",
      }}>
        {isUser ? <span style={{ whiteSpace: "pre-wrap" }}>{msg.content}</span> : <Markdown content={msg.content} />}
      </div>

      {msg.cards && msg.cards.length > 0 && (
        <div style={{ marginTop: space.sm, maxWidth: "82%", width: "100%" }}>
          {msg.cards.map((event) => (
            <div key={event.event_id} onClick={() => onCardClick(event)}>
              <RuntimeCardForEvent event={event} compact />
            </div>
          ))}
        </div>
      )}

      {msg.traceId && (
        <div onClick={() => onTraceClick(msg.traceId!)} style={{ marginTop: 4, fontSize: typo.xs, color: colors.accent, cursor: "pointer", textDecoration: "underline", paddingLeft: space.sm }}>
          View trace →
        </div>
      )}
    </div>
  );
}

function RuntimeCardForEvent({ event, compact }: { event: RuntimeEventEnvelope; compact?: boolean }) {
  const type = event.event_type || "";
  const payload = event.payload || {};

  if (type.startsWith("task.") || type === "run.started" || type === "run.completed") {
    return <TaskCard event={event} title={String(payload.task_id || payload.run_id || "Task")} status={type.replace("task.", "").replace("run.", "")} detail={payload as Record<string, unknown>} compact={compact} />;
  }
  if (type.startsWith("approval.")) {
    return <ApprovalCard event={event} title={String(payload.request_id || "Approval")} status={type.replace("approval.", "")} compact={compact}>
      {type === "approval.requested" && <ApprovalActions requestId={String(payload.request_id || "")} />}
    </ApprovalCard>;
  }
  if (type.startsWith("artifact.")) {
    return <ArtifactCard event={event} title={String(payload.artifact_id || "Artifact")} status={type.replace("artifact.", "")} detail={payload as Record<string, unknown>} compact={compact} />;
  }
  if (type.startsWith("verification.")) {
    return <VerificationCard event={event} title={String(payload.capability_id || payload.task_id || "Verification")} status={type.replace("verification.", "")} detail={payload as Record<string, unknown>} compact={compact} />;
  }
  if (type.startsWith("plan.")) {
    const stages: PlanStage[] = Array.isArray(payload.stages) ? payload.stages as PlanStage[] : [];
    return <PlanCard event={event} title={String(payload.plan_id || "Plan")} status={type.replace("plan.", "")} planStages={stages.length > 0 ? stages : undefined} compact={compact} />;
  }
  return <RuntimeCard variant="event" event={event} title={type} compact={compact} />;
}

function ApprovalActions({ requestId }: { requestId: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const handle = async (action: "approve" | "deny") => {
    setState("loading");
    try {
      await approvalAction(requestId, action);
      setState("done");
      toast.success(action === "approve" ? "Approved" : "Denied", `Request ${requestId.slice(0, 12)}...`);
    } catch (err) {
      setState("idle");
      toast.error("Failed", err instanceof Error ? err.message : "Unknown");
    }
  };
  if (state === "done") return <div style={{ marginTop: space.sm, fontSize: typo.sm, color: colors.textTertiary }}>✓ Done</div>;
  return (
    <div style={{ marginTop: space.sm, display: "flex", gap: space.sm }}>
      <button onClick={(e) => { e.stopPropagation(); handle("approve"); }} disabled={state === "loading"} style={{ padding: `${space.xs} ${space.md}`, background: colors.success, color: colors.textInverse, border: "none", borderRadius: radius.md, fontSize: typo.sm, fontWeight: typo.medium, fontFamily: typo.font, cursor: "pointer", opacity: state === "loading" ? 0.6 : 1 }}>Approve</button>
      <button onClick={(e) => { e.stopPropagation(); handle("deny"); }} disabled={state === "loading"} style={{ padding: `${space.xs} ${space.md}`, background: "transparent", color: colors.danger, border: `1px solid ${colors.danger}`, borderRadius: radius.md, fontSize: typo.sm, fontFamily: typo.font, cursor: "pointer", opacity: state === "loading" ? 0.6 : 1 }}>Deny</button>
    </div>
  );
}


function RuntimeActivity({ runId, events }: { runId: string; events: RuntimeEventEnvelope[] }) {
  const summary = summarizeRuntimeActivity(events);

  return (
    <div style={{
      marginBottom: space.lg,
      padding: `${space.md} ${space.lg}`,
      border: `1px solid ${colors.border}`,
      borderRadius: radius.lg,
      background: colors.surface,
      fontSize: typo.xs,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: colors.accent, animation: "nousPulse 1.5s infinite", flexShrink: 0 }} />
        <strong style={{ color: colors.text }}>{summary.current}</strong>
        <span style={{ flex: 1 }} />
        <span style={{ color: colors.textTertiary, fontFamily: "monospace" }}>{runId.slice(0, 8)}</span>
      </div>
      {summary.recent.length > 1 && (
        <div style={{ marginTop: space.sm, display: "grid", gap: 4, color: colors.textSecondary }}>
          {summary.recent.slice(0, -1).map((label, index) => (
            <div key={`${index}-${label}`}>✓ {label}</div>
          ))}
        </div>
      )}
      <div style={{ marginTop: space.sm, display: "flex", gap: space.lg, color: colors.textTertiary }}>
        {summary.iteration > 0 && <span>Iteration {summary.iteration}</span>}
        {summary.completedTools > 0 && <span>{summary.completedTools} tools verified</span>}
        {summary.failedTools > 0 && <span style={{ color: colors.danger }}>{summary.failedTools} failed</span>}
        {summary.artifacts > 0 && <span>{summary.artifacts} artifacts</span>}
        {summary.tokens > 0 && <span>{summary.tokens.toLocaleString()} tokens</span>}
      </div>
    </div>
  );
}


// ChatView


export function ChatView({
  conversationId, onConversationCreated, onCardClick, onTraceClick,
}: {
  conversationId?: string;
  onConversationCreated?: (conversationId: string) => void;
  onCardClick: (event: RuntimeEventEnvelope) => void;
  onTraceClick: (traceId: string) => void;
}) {
  // All state from EntityStore
  const messages = useMessages(conversationId || "");
  const activeTasks = useActiveTasks();
  const models = useModels();
  const nodes = useNodes();
  const hydrated = useStoreHydrated();

  const [localMessages, setLocalMessages] = useState<Array<{
    id: string; role: string; content: string; timestamp: string; traceId?: string; modelId?: string; cards?: RuntimeEventEnvelope[];
  }>>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [liveEvents, setLiveEvents] = useState<RuntimeEventEnvelope[]>([]);
  const [activeRunId, setActiveRunId] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!conversationId) {
      setLocalMessages([]);
      return;
    }
    let cancelled = false;
    fetchConversation(conversationId)
      .then((conversation) => {
        if (cancelled) return;
        const { messages: history, ...summary } = conversation;
        entityStore.upsertConversations([summary]);
        entityStore.upsertMessages(history || []);
        setLocalMessages([]);
      })
      .catch((error) => {
        if (!cancelled) {
          toast.error(
            "Conversation could not be loaded",
            error instanceof Error ? error.message : "Unknown error",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  // Seed welcome message (only if hydrated with no messages)
  useEffect(() => {
    if (hydrated && messages.length === 0 && localMessages.length === 0) {
      setLocalMessages([{
        id: "welcome",
        role: "assistant",
        content: "Good to see you. I'm APEIR — I plan, execute, and verify tasks across your nodes.\n\nYou can ask me to:\n- **Plan** a multi-step workflow with dependencies\n- **Execute** tasks on specific models or nodes\n- **Verify** results with automated checks\n\nWhat would you like to do?",
        timestamp: new Date().toISOString(),
      }]);
    }
  }, [hydrated, messages.length, localMessages.length]);

  // Merge store messages with local ephemeral messages
  const allMessages = [
    ...messages.map((m) => ({
      id: m.id, role: m.role, content: m.content,
      timestamp: m.created_at, traceId: m.trace_id,
      modelId: m.model_id, cards: m.cards,
    })),
    ...localMessages,
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allMessages, loading]);


  // Send handler — calls real API, stores real data


  const handleSend = useCallback(async (text: string, attachments: ComposerAttachment[], constraints: ComposerConstraints) => {
    const userMsg = { id: `u_${Date.now()}`, role: "user", content: text, timestamp: new Date().toISOString() };
    setLocalMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setStreaming(true);
    setLiveEvents([]);
    const requestId = crypto.randomUUID();
    setActiveRunId(requestId);

    const controller = new AbortController();
    abortRef.current = controller;
    const appendEvent = (event: RuntimeEventEnvelope) => {
      setLiveEvents((current) => {
        if (current.some((item) => item.event_id === event.event_id)) return current;
        return [...current, event].sort((a, b) => a.sequence - b.sequence).slice(-80);
      });
    };
    const subscription = subscribeRunEvents(
      requestId,
      (event) => appendEvent(event as RuntimeEventEnvelope),
      { intervalMs: 500 },
    );

    try {
      const result = await runPrompt(
        text,
        constraints.model_id,
        conversationId,
        constraints.agent_mode || "agent",
        controller.signal,
        requestId,
      );
      if (result.status === "failed") {
        throw new Error(describeRuntimeFailure(result.message || ""));
      }
      if (result.conversation_id && result.conversation_id !== conversationId) {
        onConversationCreated?.(result.conversation_id);
      }
      const content = result.message || "Runtime completed without a text response.";
      const traceId = result?.trace_id;
      const runId = result?.run_id || requestId;
      let terminalEvents: RuntimeEventEnvelope[] = [];
      try {
        const page = await fetchRunEvents(requestId, 0);
        terminalEvents = page.events as RuntimeEventEnvelope[];
        terminalEvents.forEach(appendEvent);
      } catch {
        // The response remains authoritative if telemetry replay is unavailable.
      }

      const asstMsg = {
        id: `a_${Date.now()}`, role: "assistant", content,
        timestamp: new Date().toISOString(), traceId: runId || traceId,
        modelId: constraints.model_id || "default",
        cards: terminalEvents.filter((event) =>
          event.event_type.startsWith("approval.")
          || event.event_type.startsWith("artifact.")
          || event.event_type === "run.failed",
        ),
      };
      setLocalMessages((prev) => [...prev, asstMsg]);
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      setLocalMessages((prev) => [...prev, {
        id: `e_${Date.now()}`, role: "system",
        content: `Error: ${err instanceof Error ? err.message : "Request failed"}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      subscription.close();
      setLoading(false);
      setStreaming(false);
      setActiveRunId("");
      abortRef.current = null;
    }
  }, [conversationId, onConversationCreated]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setLoading(false);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: colors.bg }}>
      {/* Header */}
      <div style={{
        padding: `${space.md} ${space.xl}`, borderBottom: `1px solid ${colors.borderLight}`,
        background: colors.surface, display: "flex", alignItems: "center", gap: space.md,
      }}>
        <h1 style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text, margin: 0 }}>APEIR</h1>
        <span style={{ fontSize: typo.xs, color: colors.textTertiary }}>
          {activeTasks.length > 0 ? `${activeTasks.length} active` : "Ready"}
        </span>
        {loading && <span style={{ fontSize: typo.xs, color: colors.accent, animation: "nousPulse 1.5s infinite" }}>Running</span>}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: `${space.xl} ${space.xl} 0`, scrollBehavior: "smooth" }}>
        {!hydrated ? (
          <div style={{ padding: space.xl, color: colors.textTertiary, fontSize: typo.sm }}>
            Loading conversation...
          </div>
        ) : (
          allMessages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} onCardClick={onCardClick} onTraceClick={onTraceClick} />
          ))
        )}

        {loading && <RuntimeActivity runId={activeRunId} events={liveEvents} />}

        {/* Active task cards */}
        {activeTasks.length > 0 && (
          <div style={{ marginBottom: space.lg }}>
            <div style={{ fontSize: typo.xs, fontWeight: typo.semibold, color: colors.textTertiary, textTransform: "uppercase", marginBottom: space.sm }}>Active Tasks</div>
            {activeTasks.slice(0, 5).map((t) => (
              <TaskCard key={t.id} title={t.name || t.id} status={t.status}
                subtitle={`${t.model_id || "auto"} · ${t.steps.length} steps`}
                progress={t.progress_pct} compact
              />
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <Composer
        onSend={handleSend}
        onStop={handleStop}
        disabled={loading && !streaming}
        streaming={streaming}
        models={models}
        nodes={nodes}
        conversationId={conversationId}
      />
    </div>
  );
}
