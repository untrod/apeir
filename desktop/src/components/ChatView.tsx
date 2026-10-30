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
import { btnSecondary, colors, typo, radius, space, fadeIn } from "../design";
import { entityStore } from "../store";
import { useMessages, useActiveTasks, useModels, useNodes, useStoreHydrated, useRuntimeConfigVersion } from "../store";
import type { RuntimeEventEnvelope, Conversation, Message as MessageType } from "../store";
import {
  approvalAction,
  captureRuntimeConnection,
  describeRuntimeFailure,
  fetchConversation,
  fetchRunEvents,
  getConfig,
  runPrompt,
  subscribeRunEvents,
} from "../lib/api";
import {
  RuntimeCard, TaskCard, ApprovalCard, VerificationCard, ArtifactCard, PlanCard,
  type PlanStage,
} from "./RuntimeCard";
import { Markdown } from "./Markdown";
import { Composer, CHAT_ATTACHMENTS_UNAVAILABLE, CHAT_CONSTRAINTS_UNAVAILABLE, type ComposerAttachment, type ComposerConstraints } from "./Composer";
import { toast } from "./Toast";
import { runtimeActivityLabel, summarizeRuntimeActivity } from "../lib/runtimeActivity";
import { measuredUsage } from "../lib/usageAccounting";
import { ContextInspector } from "./ContextInspector";


// Message Bubble


function MessageBubble({
  msg, onCardClick, onTraceClick, onContextClick, onActivityClick, locale = "en",
}: {
  msg: { id: string; role: string; content: string; timestamp: string; traceId?: string; runId?: string; modelId?: string; cards?: RuntimeEventEnvelope[] };
  onCardClick: (event: RuntimeEventEnvelope) => void;
  onTraceClick: (traceId: string) => void;
  onContextClick: (runId: string) => void;
  onActivityClick: (runId: string) => void;
  locale?: "en" | "zh";
}) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div style={{ textAlign: "center", padding: `${space.sm} 0`, fontSize: msg.runId ? typo.sm : typo.xs, color: msg.runId ? colors.textSecondary : colors.textTertiary, overflowWrap: "anywhere" }}>
        {msg.content}
        {msg.runId && <div style={{ marginTop: space.sm }}>
          <code>{msg.runId}</code>{" "}
          <button onClick={() => onActivityClick(msg.runId!)} style={btnSecondary}>{locale === "zh" ? "执行记录" : "Execution activity"}</button>
        </div>}
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
      {msg.runId && !isUser && <button onClick={() => onContextClick(msg.runId!)} style={{ ...btnSecondary, marginTop: space.sm }}>Inspect model input</button>}
      {msg.runId && !isUser && <button onClick={() => onActivityClick(msg.runId!)} style={{ ...btnSecondary, marginTop: space.sm }}>Execution activity</button>}
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
      {type === "approval.requested" && <ApprovalActions key={String(payload.request_id || "")} requestId={String(payload.request_id || "")} />}
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
  const [connection] = useState(captureRuntimeConnection);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  const current = () => {
    connection();
    if (!active.current) throw new Error("Approval view closed; review the original request again");
  };
  const handle = async (action: "approve" | "deny") => {
    setState("loading");
    try {
      current();
      await approvalAction(requestId, action, current);
      current();
      setState("done");
      toast.success(action === "approve" ? "Approved" : "Denied", `Request ${requestId.slice(0, 12)}...`);
    } catch (err) {
      try { current(); } catch { return; }
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


function RuntimeActivity({ runId, events, running, connection, locale = "en", inspect }: { runId: string; events: RuntimeEventEnvelope[]; running: boolean; connection: "connecting" | "live" | "reconnecting"; locale?: "en" | "zh"; inspect: () => void }) {
  const summary = summarizeRuntimeActivity(events);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const fields = ["provider_id", "model_id", "tool", "tool_call_id", "capability_id", "execution_scope", "agent_invocation_id", "usage_request_id", "receipt_id", "proposal_id", "approval_request_id"];

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
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: colors.accent, animation: running ? "nousPulse 1.5s infinite" : undefined, flexShrink: 0 }} />
        <strong style={{ color: colors.text }}>{!running && events.length === 0 ? t("No recorded activity", "暂无执行记录") : summary.current}</strong>
        <span style={{ flex: 1 }} />
        <span style={{ color: colors.textTertiary, fontFamily: "monospace" }}>{runId.slice(0, 8)}</span>
      </div>
      {summary.recent.length > 1 && (
        <div style={{ marginTop: space.sm, display: "grid", gap: 4, color: colors.textSecondary }}>
          {summary.recent.slice(0, -1).map((label, index) => (
            <div key={`${index}-${label}`}>· {label}</div>
          ))}
        </div>
      )}
      <div style={{ marginTop: space.sm, display: "flex", gap: space.lg, color: colors.textTertiary }}>
        {summary.iteration > 0 && <span>Iteration {summary.iteration}</span>}
        {summary.completedTools > 0 && <span>{summary.completedTools} tools completed</span>}
        {summary.failedTools > 0 && <span style={{ color: colors.danger }}>{summary.failedTools} failed</span>}
        {summary.unknownTools > 0 && <span>{summary.unknownTools} UNKNOWN</span>}
        {summary.artifacts > 0 && <span>{summary.artifacts} artifacts</span>}
        <span>{summary.tokens === null ? "Token UNKNOWN" : `${summary.tokens.toLocaleString()} tokens`}</span>
      </div>
      {running && <div role="status" style={{ marginTop: space.sm, color: connection === "reconnecting" ? colors.warning : colors.textTertiary }}>
        {connection === "reconnecting" ? t("Event connection interrupted; reconnecting. The task may still be running.", "事件连接中断，正在重连；任务可能仍在运行。") : connection === "connecting" ? t("Waiting for recorded activity…", "等待执行记录…") : t("Receiving recorded activity", "正在接收执行记录")}
      </div>}
      {events.length > 0 && <details style={{ marginTop: space.sm }}>
        <summary style={{ cursor: "pointer", color: colors.textSecondary }}>{t("Activity details", "处理详情")} · {events.length}</summary>
        <ol style={{ maxHeight: 240, overflowY: "auto", paddingLeft: space.lg }}>
          {events.map(event => <li key={event.event_id} style={{ marginTop: space.sm }}>
            <div>{runtimeActivityLabel(event)}</div>
            {fields.map(field => {
              const value = event.payload?.[field];
              return typeof value === "string" && value ? <div key={field} style={{ color: colors.textTertiary, overflowWrap: "anywhere" }}>{field}: {value.slice(0, 240)}</div> : null;
            })}
            {event.event_type.startsWith("model.invocation.") && event.event_type !== "model.invocation.started" && <div style={{ color: colors.textTertiary }}>
              {t("Cost", "费用")}: {measuredUsage(event.payload?.cost_usd, event.payload?.cost_measurement, true)}
              {typeof event.payload?.latency_ms === "number" && Number.isFinite(event.payload.latency_ms) && event.payload.latency_ms >= 0 && <> · {event.payload.latency_ms} ms</>}
            </div>}
          </li>)}
        </ol>
        <button style={btnSecondary} onClick={inspect}>{t("Inspect model input", "检查模型输入")}</button>
      </details>}
    </div>
  );
}


// ChatView


type ChatViewProps = {
  locale?: "en" | "zh";
  conversationId?: string;
  onConversationCreated?: (conversationId: string) => void;
  onCardClick: (event: RuntimeEventEnvelope) => void;
  onTraceClick: (traceId: string) => void;
  workspaceFile?: { path: string; sha256: string; controller?: string };
  readOnly?: boolean;
  onProposalCreated?: (proposalId: string) => void;
  onClearWorkspaceFile?: () => void;
};

export function ChatView(props: ChatViewProps) {
  const connectionVersion = useRuntimeConfigVersion();
  return <ChatSession key={JSON.stringify([connectionVersion, props.conversationId || ""])} {...props} />;
}

function ChatSession({
  conversationId, onConversationCreated, onCardClick, onTraceClick,
  workspaceFile, readOnly = false, onClearWorkspaceFile, onProposalCreated, locale = "en",
}: ChatViewProps) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  // All state from EntityStore
  const messages = useMessages(conversationId || "");
  const activeTasks = useActiveTasks();
  const models = useModels();
  const nodes = useNodes();
  const hydrated = useStoreHydrated();

  const [localMessages, setLocalMessages] = useState<Array<{
    id: string; role: string; content: string; timestamp: string; traceId?: string; runId?: string; modelId?: string; cards?: RuntimeEventEnvelope[];
  }>>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [liveEvents, setLiveEvents] = useState<RuntimeEventEnvelope[]>([]);
  const [activeRunId, setActiveRunId] = useState("");
  const [eventConnection, setEventConnection] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const [activityHistory, setActivityHistory] = useState<{ runId: string; events: RuntimeEventEnvelope[]; loading: boolean; error: boolean } | null>(null);
  const historyRequest = useRef(0);
  const [contextView, setContextView] = useState<{ runId: string; controller: string } | null>(null);
  const inspectContext = (runId: string) => setContextView({ runId, controller: getConfig().url });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const subscriptionRef = useRef<ReturnType<typeof subscribeRunEvents> | null>(null);
  const active = useRef(true);
  const [connection] = useState(captureRuntimeConnection);
  const currentView = useCallback(() => {
    try { connection(); return active.current; } catch { return false; }
  }, [connection]);
  const recordStoppedWait = useCallback((runId: string) => {
    if (!runId) return;
    setLocalMessages((prev) => prev.some(message => message.id === `stopped_wait_${runId}`) ? prev : [...prev, {
      id: `stopped_wait_${runId}`,
      role: "system",
      content: locale === "zh"
        ? "已停止等待。尚未确认 Runtime 取消，原始请求可能仍在执行或产生费用。再次提交前，请先查看原始执行记录。"
        : "Stopped waiting. Runtime cancellation is unconfirmed; the original request may still be running or incur cost. Inspect its recorded activity before submitting it again.",
      timestamp: new Date().toISOString(),
      runId,
    }]);
  }, [locale]);
  const inspectActivity = async (runId: string) => {
    if (!currentView()) return;
    const request = ++historyRequest.current;
    setActivityHistory({ runId, events: [], loading: true, error: false });
    try {
      const page = await fetchRunEvents(runId, 0);
      if (!currentView() || request !== historyRequest.current) return;
      setActivityHistory({ runId, events: page.events as RuntimeEventEnvelope[], loading: false, error: false });
    } catch {
      if (currentView() && request === historyRequest.current) setActivityHistory({ runId, events: [], loading: false, error: true });
    }
  };
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      abortRef.current?.abort();
      subscriptionRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!conversationId) {
      setLocalMessages([]);
      return;
    }
    let cancelled = false;
    fetchConversation(conversationId)
      .then((conversation) => {
        if (cancelled || !currentView()) return;
        const { messages: history, ...summary } = conversation;
        entityStore.upsertConversations([summary]);
        entityStore.upsertMessages(history || []);
        setLocalMessages([]);
      })
      .catch((error) => {
        if (!cancelled && currentView()) {
          toast.error(
            "Conversation could not be loaded",
            error instanceof Error ? error.message : "Unknown error",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, currentView]);

  // Merge store messages with local ephemeral messages
  const allMessages = [
    ...messages.map((m) => ({
      id: m.id, role: m.role, content: m.content,
      timestamp: m.created_at, traceId: m.trace_id,
      modelId: m.model_id, runId: m.run_id, cards: m.cards,
    })),
    ...localMessages,
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  // Unrelated Runtime snapshots must not move a reader's chat position.
  const latestMessage = allMessages[allMessages.length - 1];
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [latestMessage?.id, latestMessage?.content, latestMessage?.cards?.length, loading]);


  // Send handler — calls real API, stores real data


  const handleSend = useCallback(async (text: string, attachments: ComposerAttachment[], constraints: ComposerConstraints) => {
    if (!currentView()) return;
    const unsupported = attachments.length > 0 ? CHAT_ATTACHMENTS_UNAVAILABLE
      : constraints.node_id || (constraints.privacy_level && constraints.privacy_level !== "standard") || constraints.budget_limit_usd !== undefined
        ? CHAT_CONSTRAINTS_UNAVAILABLE : "";
    if (unsupported) {
      setLocalMessages(prev => [...prev, { id: `e_${Date.now()}`, role: "system", content: unsupported, timestamp: new Date().toISOString() }]);
      return;
    }
    if (workspaceFile?.controller && workspaceFile.controller !== getConfig().url) {
      setLocalMessages(prev => [...prev, { id: `e_${Date.now()}`, role: "system", content: "Controller changed; remove the original file reference before continuing.", timestamp: new Date().toISOString() }]);
      return;
    }
    if (abortRef.current && !abortRef.current.signal.aborted) recordStoppedWait(activeRunId);
    const userMsg = { id: `u_${Date.now()}`, role: "user", content: text, timestamp: new Date().toISOString() };
    setLocalMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setStreaming(true);
    setLiveEvents([]);
    setEventConnection("connecting");
    const requestId = crypto.randomUUID();
    setActiveRunId(requestId);

    abortRef.current?.abort();
    subscriptionRef.current?.close();
    const controller = new AbortController();
    abortRef.current = controller;
    const isCurrent = () => currentView() && abortRef.current === controller && !controller.signal.aborted;
    const appendEvent = (event: RuntimeEventEnvelope) => {
      if (!isCurrent()) return;
      setLiveEvents((current) => {
        if (current.some((item) => item.event_id === event.event_id)) return current;
        return [...current, event].sort((a, b) => a.sequence - b.sequence).slice(-80);
      });
    };
    const subscription = subscribeRunEvents(
      requestId,
      (event) => appendEvent(event as RuntimeEventEnvelope),
      { intervalMs: 500, onStatus: status => { if (isCurrent()) setEventConnection(status); } },
    );
    subscriptionRef.current = subscription;

    try {
      const result = await runPrompt(
        text,
        constraints.model_id,
        conversationId,
        readOnly ? "read_only" : constraints.agent_mode || "agent",
        controller.signal,
        requestId,
        workspaceFile ? [{ path: workspaceFile.path, sha256: workspaceFile.sha256 }] : undefined,
      );
      if (!isCurrent()) return;
      if (result.status === "failed" || result.status === "selected_input_rejected") {
        throw new Error(describeRuntimeFailure(result.message || ""));
      }
      if (result.status === "waiting_approval" && result.result?.proposal_id) onProposalCreated?.(result.result.proposal_id);
      if (result.conversation_id && result.conversation_id !== conversationId) {
        onConversationCreated?.(result.conversation_id);
      }
      const content = result.message || "Runtime completed without a text response.";
      const traceId = result?.trace_id;
      const runId = result?.run_id || requestId;
      let terminalEvents: RuntimeEventEnvelope[] = [];
      try {
        const page = await fetchRunEvents(requestId, 0);
        if (!isCurrent()) return;
        terminalEvents = page.events as RuntimeEventEnvelope[];
        terminalEvents.forEach(appendEvent);
      } catch {
        // The response remains authoritative if telemetry replay is unavailable.
      }

      if (!isCurrent()) return;
      const asstMsg = {
        id: `a_${Date.now()}`, role: "assistant", content,
        timestamp: new Date().toISOString(), traceId, runId,
        modelId: constraints.model_id || "default",
        cards: terminalEvents.filter((event) =>
          event.event_type.startsWith("approval.")
          || event.event_type.startsWith("artifact.")
          || event.event_type === "run.failed",
        ),
      };
      setLocalMessages((prev) => [...prev, asstMsg]);
    } catch (err: any) {
      if (!isCurrent() || err?.name === "AbortError") return;
      setLocalMessages((prev) => [...prev, {
        id: `e_${Date.now()}`, role: "system",
        content: `Error: ${err instanceof Error ? err.message : "Request failed"}`,
        runId: requestId,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      subscription.close();
      if (subscriptionRef.current === subscription) subscriptionRef.current = null;
      if (abortRef.current === controller) {
        abortRef.current = null;
        if (currentView()) {
          setLoading(false);
          setStreaming(false);
        }
      }
    }
  }, [conversationId, onConversationCreated, workspaceFile, readOnly, onProposalCreated, currentView, activeRunId, recordStoppedWait]);

  const handleStop = useCallback(() => {
    if (!currentView() || !abortRef.current || abortRef.current.signal.aborted) return;
    abortRef.current.abort();
    subscriptionRef.current?.close();
    recordStoppedWait(activeRunId);
    setStreaming(false);
    setLoading(false);
  }, [activeRunId, currentView, recordStoppedWait]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: colors.bg }}>
      {/* Header */}
      <div style={{
        padding: `${space.md} ${space.xl}`, borderBottom: `1px solid ${colors.borderLight}`,
        background: colors.surface, display: "flex", alignItems: "center", gap: space.md,
      }}>
        <h1 style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text, margin: 0 }}>APEIR</h1>
        {readOnly && <span style={{ fontSize: typo.xs, color: colors.textSecondary }}>Read-only collaboration</span>}
        <span style={{ fontSize: typo.xs, color: colors.textTertiary }}>
          {!hydrated && !readOnly ? t("Connecting", "连接中") : activeTasks.length > 0 ? t(`${activeTasks.length} active`, `${activeTasks.length} 项进行中`) : models.length ? t(`${models.length} models`, `${models.length} 个模型`) : t("No models configured", "尚未配置模型")}
        </span>
        {loading && <span style={{ fontSize: typo.xs, color: colors.accent, animation: "nousPulse 1.5s infinite" }}>Running</span>}
        {activeRunId && <button onClick={() => inspectContext(activeRunId)} style={btnSecondary}>Inspect active input</button>}
      </div>
      {contextView && <ContextInspector {...contextView} onClose={() => setContextView(null)} />}
      {workspaceFile && <div aria-label="Selected workspace reference" style={{ padding: space.md, overflowWrap: "anywhere", fontSize: typo.xs }}>
        {workspaceFile.path} · SHA-256 {workspaceFile.sha256}<br />
        File content is not automatically sent. Send requests the saved version; current read and provider transfer permission are required.
        <button onClick={onClearWorkspaceFile} style={{ marginLeft: space.sm }}>Remove reference</button>
      </div>}

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: `${space.xl} ${space.xl} 0`, scrollBehavior: "smooth" }}>
        {!hydrated && !readOnly ? (
          <div style={{ padding: space.xl, color: colors.textTertiary, fontSize: typo.sm }}>
            Loading conversation...
          </div>
        ) : allMessages.length === 0 ? (
          <div style={{ display: "grid", placeContent: "center", minHeight: "45%", padding: space.xl, textAlign: "center", gap: space.sm }}>
            <h2 style={{ fontSize: typo.xl, fontWeight: typo.medium, color: colors.text }}>{t("What would you like to work on?", "今天想完成什么？")}</h2>
            <p style={{ fontSize: typo.sm, color: colors.textSecondary }}>{models.length ? readOnly ? t("Ask about a saved project file.", "分析已保存的项目文件。") : t("Ask a question or describe a task.", "提出问题，或描述你的任务。") : t("Connect a model to start a conversation.", "连接模型后即可开始对话。")}</p>
          </div>
        ) : (
          allMessages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} onCardClick={onCardClick} onTraceClick={onTraceClick} onContextClick={inspectContext} onActivityClick={inspectActivity} locale={locale} />
          ))
        )}

        {(loading || liveEvents.length > 0) && <RuntimeActivity runId={activeRunId} events={liveEvents} running={loading} connection={eventConnection} locale={locale} inspect={() => inspectContext(activeRunId)} />}
        {activityHistory && <section aria-label={t("Recorded execution activity", "原始执行记录")}>
          <button style={btnSecondary} onClick={() => { historyRequest.current += 1; setActivityHistory(null); }}>{t("Close activity", "关闭记录")}</button>
          {activityHistory.loading ? <p role="status">{t("Loading recorded events…", "正在读取执行记录…")}</p> : activityHistory.error ? <p role="alert">{t("Recorded activity unavailable. The task has not been resubmitted.", "执行记录暂不可读取；未重新提交任务。")}</p> : <>
            <RuntimeActivity runId={activityHistory.runId} events={activityHistory.events} running={false} connection="live" locale={locale} inspect={() => inspectContext(activityHistory.runId)} />
            {!activityHistory.events.length && <p>{t("No recorded events returned.", "未返回执行记录。")}</p>}
            {activityHistory.events.length >= 200 && <p>{t("Showing the first 200 recorded events; use the original Run inspector for further evidence.", "显示前 200 条记录；更多证据请查看原始运行。")}</p>}
          </>}
        </section>}

        {/* Active task cards */}
        {activeTasks.length > 0 && (
          <div style={{ marginBottom: space.lg }}>
            <div style={{ fontSize: typo.xs, fontWeight: typo.semibold, color: colors.textTertiary, textTransform: "uppercase", marginBottom: space.sm }}>Active Tasks</div>
            {activeTasks.slice(0, 5).map((t) => (
              <TaskCard key={t.id} title={t.name || t.id} status={t.status}
                subtitle={`${t.model_id || "auto"} · ${t.steps_reported === false ? "Steps UNKNOWN" : `${t.steps.length} steps`}`}
                progress={t.progress_reported === false ? undefined : t.progress_pct} compact
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
        stopLabel={t("Stop waiting", "停止等待")}
        models={models}
        nodes={nodes}
        conversationId={conversationId}
        readOnly={readOnly}
        attachmentsSupported={false}
        extendedConstraintsSupported={false}
      />
    </div>
  );
}
